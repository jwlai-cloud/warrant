"""HTTP surface.

POST /v1/warrant       - request a warrant for an agent-to-agent call
GET  /v1/warrant/{id}  - look one up (callees verify what they were handed)
GET  /v1/grant-requests          - open and decided grant requests
POST /v1/grant-requests          - a refused agent raises one
POST /v1/grant-requests/{id}/decision - the steward approves or declines
GET  /v1/audit     - the decision log
GET  /v1/model     - the architecture model as a graph (for the UI)
GET  /healthz      - liveness + which tier is currently serving
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict

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
            "served_by": {"tier": d.tier_used, "provider": d.provider_kind,
                          "latency_ms": round(d.latency_ms, 2)},
            "explained_by": {"tier": d.justify_tier, "provider": d.justify_provider,
                             "latency_ms": round(d.justify_ms, 2)},
            "issued_at": d.issued_at,
            "expires_at": d.expires_at,
        },
    )


@app.get("/v1/warrant/{warrant_id}")
async def get_warrant(warrant_id: str):
    """Look one warrant up. This is what a callee calls to verify that the
    warrant a caller presented is real, current, and actually covers the data
    it is about to hand over. Without it, `governed_call` is honour-system:
    a caller could skip asking and the boundary would enforce nothing."""
    assert _svc is not None
    for e in audit.read_all(_svc.config.audit_path, limit=10_000):
        if e["id"] == warrant_id:
            return e
    return JSONResponse(status_code=404, content={"error": "unknown warrant"})


class GrantRequestIn(BaseModel):
    capability: str
    data_entity: str
    requested_by: str
    reason: str = ""
    blocking: int = 0


class DecisionIn(BaseModel):
    decided_by: str          # the org unit claiming to steward the entity
    note: str = ""


@app.get("/v1/grant-requests")
async def list_grant_requests():
    assert _svc is not None
    return {"requests": [asdict(r) for r in _svc.requests.all()]}


@app.post("/v1/grant-requests")
async def raise_grant_request(body: GrantRequestIn):
    """Raised by a refused agent's replan step."""
    assert _svc is not None
    try:
        r = _svc.requests.raise_request(_svc.model, **body.model_dump())
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return JSONResponse(status_code=201, content=asdict(r))


@app.post("/v1/grant-requests/{request_id}/decision")
async def decide_grant_request(request_id: str, body: DecisionIn,
                               approve: bool = True):
    """The only endpoint in WARRANT that creates authority.

    The steward check is modelled, not authenticated: it verifies the claimed
    approver stewards the entity, which is not proof of who is calling. Real
    authn belongs in front of this in any deployment - see engine/requests.py.
    """
    assert _svc is not None
    try:
        r = _svc.requests.decide(_svc.model, request_id, approve=approve,
                                 decided_by=body.decided_by, note=body.note)
    except PermissionError as exc:
        return JSONResponse(status_code=403, content={"error": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return asdict(r)


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
