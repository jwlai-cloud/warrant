"""A serving agent: holds data for one organisation unit, hands it over only
against a warrant that covers it.

`inventory-reconciler` and `roster-planner` are both this. Neither needs a
planning loop - they are callees. The planner lives in `auditor.py`.

The important line in here is the `verify_warrant` call. It is what stops the
seam being honour-system: this agent does not trust that a caller presenting a
warrant id was actually authorised, it asks the plane, and it asks specifically
whether the warrant covers the entities in the response it is about to send.
"""
from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .base import WarrantRejected, verify_warrant
from .fixtures import DATASETS


class DataRequest(BaseModel):
    warrant_id: str
    caller: str
    purpose: str = ""


def make_serving_agent(agent_id: str, plane_url: str) -> FastAPI:
    dataset = DATASETS[agent_id]
    app = FastAPI(title=f"WARRANT agent: {agent_id}", version="0.1.0")
    client = httpx.AsyncClient(timeout=10.0)

    @app.get("/whoami")
    async def whoami():
        return {"agent": agent_id, "serves": sorted(dataset)}

    @app.post("/data")
    async def data(req: DataRequest):
        # Serve only what this warrant already says the call touches. Starting
        # from the warrant rather than from the request means a caller cannot
        # widen the response by asking for more.
        try:
            w = await client.get(
                f"{plane_url.rstrip('/')}/v1/warrant/{req.warrant_id}"
            )
        except httpx.HTTPError as exc:
            # Fail closed: if the authority is unreachable we serve nothing.
            return JSONResponse(status_code=503,
                                content={"error": f"plane unreachable: {exc}"})
        if w.status_code != 200:
            return JSONResponse(status_code=403,
                                content={"error": "unknown warrant"})

        covered = [e for e in w.json().get("entities_touched", []) if e in dataset]

        try:
            await verify_warrant(
                client, plane_url, req.warrant_id,
                expect_caller=req.caller,
                expect_callee=agent_id,
                serving_entities=covered,
            )
        except WarrantRejected as exc:
            return JSONResponse(status_code=403, content={"error": str(exc)})

        if not covered:
            return JSONResponse(
                status_code=403,
                content={"error": f"warrant covers nothing {agent_id} holds"},
            )

        return {"served_by": agent_id,
                "entities": covered,
                "rows": {e: dataset[e] for e in covered}}

    @app.on_event("shutdown")
    async def _close():
        await client.aclose()

    return app
