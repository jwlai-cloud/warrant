"""HTTP surface.

POST /v1/warrant   - request a warrant for an agent-to-agent call
GET  /v1/audit     - the decision log
GET  /v1/model     - the architecture model as a graph (for the UI)
GET  /healthz      - liveness + which tier is currently serving
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..engine import WarrantRequest, audit
from ..service import WarrantService

_svc: WarrantService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _svc
    _svc = WarrantService()
    yield
    await _svc.aclose()


app = FastAPI(title="WARRANT", version="0.1.0", lifespan=lifespan)


class WarrantIn(BaseModel):
    caller_agent: str
    callee_agent: str
    purpose: str = ""
    payload: str = ""


@app.post("/v1/warrant")
async def request_warrant(body: WarrantIn):
    assert _svc is not None
    d = await _svc.evaluate(WarrantRequest(**body.model_dump()))
    return JSONResponse(
        status_code=200 if d.granted else 403,
        content={
            "id": d.id,
            "granted": d.granted,
            "headline": d.headline(),
            "justification": d.justification,
            "entities_touched": d.entities_touched,
            "missing_grants": [{"capability": c, "data_entity": e}
                               for c, e in d.missing_grants],
            "reasons": [{"code": r.code, "detail": r.detail} for r in d.reasons],
            "served_by": {"tier": d.tier_used, "provider": d.provider_kind},
            "issued_at": d.issued_at,
        },
    )


@app.get("/v1/audit")
async def get_audit(limit: int = 50):
    assert _svc is not None
    return {"entries": audit.read_all(_svc.config.audit_path, limit)}


@app.get("/v1/model")
async def get_model():
    assert _svc is not None
    m = _svc.model
    return {
        "org_units": [o.model_dump() for o in m.org_units.values()],
        "capabilities": [c.model_dump() for c in m.capabilities.values()],
        "data_entities": [e.model_dump() for e in m.data_entities.values()],
        "agents": [a.model_dump() for a in m.agents.values()],
        "grants": [g.model_dump() for g in m.grants],
    }


@app.get("/healthz")
async def healthz():
    assert _svc is not None
    return {
        "ok": True,
        "tiers": {name: {"kind": cfg.kind, "model": cfg.model}
                  for name, cfg in _svc.config.tiers.items()},
    }
