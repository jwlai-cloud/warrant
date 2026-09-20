"""HTTP surface.

POST /v1/warrant       - request a warrant for an agent-to-agent call
GET  /v1/warrant/{id}  - look one up (callees verify what they were handed)
GET  /v1/grant-requests          - open and decided grant requests
POST /v1/grant-requests          - a refused agent raises one
POST /v1/grant-requests/{id}/decision - the steward approves or declines
POST /v1/demo/run                - run the Expense Auditor against the live plane
GET  /v1/audit     - the decision log
GET  /v1/model     - the architecture model as a graph (for the UI)
GET  /healthz      - liveness + which tier is currently serving
GET  /            - the console
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Header
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..engine import WarrantRequest, audit
from ..model import load_model
from ..service import WarrantService

_svc: WarrantService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _svc
    _svc = WarrantService()
    yield
    await _svc.aclose()


app = FastAPI(title="WARRANT", version="0.1.0", lifespan=lifespan)

_STATIC = Path(__file__).parent / "static"
if _STATIC.exists():
    app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/", include_in_schema=False)
async def console():
    """The console IS the product surface, so it ships in the same container as
    the plane it talks to - one URL for a judge to open (PRD P0-10)."""
    return FileResponse(_STATIC / "index.html")


def _demo_guard() -> JSONResponse | None:
    """404 rather than 403 when demo routes are off, so they are invisible
    outside a demo deployment. /v1/demo/reset deletes the audit log - which is
    also the warrant store - so it must not exist in a real one."""
    assert _svc is not None
    if not _svc.config.demo_mode:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})
    return None


def _resolve_caller(claimed: str, authorization: str | None) -> str | JSONResponse:
    """Bind the caller's identity to the transport, not the request body.

    With `agent_auth: disabled` the caller_agent field is taken on trust, which
    means any client can request a warrant AS any agent - and the callee-side
    check in agents/base.py compares against that same self-asserted value, so
    it inherits the same trust. Demo profiles opt into that explicitly; the
    code default is `required`.
    """
    assert _svc is not None
    if _svc.config.agent_auth == "disabled":
        return claimed
    token = ""
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    agent = _svc.config.agent_tokens.get(token) if token else None
    if agent is None:
        return JSONResponse(status_code=401,
                            content={"error": "agent bearer token required"})
    if claimed and claimed != agent:
        return JSONResponse(
            status_code=403,
            content={"error": f"token identifies '{agent}', not '{claimed}'"})
    return agent


class WarrantIn(BaseModel):
    # Bounded where they enter, not in the prompt builder - the same values also
    # reach the audit line and the justification prompt, and only `payload` was
    # ever truncated.
    caller_agent: str = Field(min_length=1, max_length=128)
    callee_agent: str = Field(min_length=1, max_length=128)
    purpose: str = Field("", max_length=2000)
    payload: str = Field("", max_length=8000)


@app.post("/v1/warrant")
async def request_warrant(body: WarrantIn, authorization: str | None = Header(None)):
    assert _svc is not None
    caller = _resolve_caller(body.caller_agent, authorization)
    if isinstance(caller, JSONResponse):
        return caller
    req = body.model_dump()
    req["caller_agent"] = caller
    d = await _svc.evaluate(WarrantRequest(**req))
    return JSONResponse(
        status_code=200 if d.granted else 403,
        content={
            "id": d.id,
            "granted": d.granted,
            "headline": d.headline(),
            "justification": d.justification,
            "entities_touched": d.entities_touched,
            "decisive_exclusions": d.decisive_exclusions,
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
def get_warrant(warrant_id: str):
    """Look one warrant up. This is what a callee calls to verify that the
    warrant a caller presented is real, current, and actually covers the data
    it is about to hand over. Without it, `governed_call` is honour-system:
    a caller could skip asking and the boundary would enforce nothing.

    Deliberately a plain `def`: it does blocking file I/O, and every callee
    verification calls it, so on the event loop it would stall every other
    request. FastAPI runs sync handlers in a threadpool.
    """
    assert _svc is not None
    e = audit.find(_svc.config.audit_path, warrant_id)
    if e is not None:
        return e
    return JSONResponse(status_code=404, content={"error": "unknown warrant"})


class GrantRequestIn(BaseModel):
    capability: str = Field(min_length=1, max_length=128)
    data_entity: str = Field(min_length=1, max_length=128)
    requested_by: str = Field(min_length=1, max_length=128)
    # Rendered to a steward as the basis for approving, so bounded.
    reason: str = Field("", max_length=2000)
    blocking: int = Field(0, ge=0, le=100_000)


class DecisionIn(BaseModel):
    decided_by: str          # the org unit claiming to steward the entity
    # REQUIRED, and deliberately has no default. It used to be a bare `approve:
    # bool = True` in the signature, which FastAPI bound as a QUERY parameter -
    # so a well-formed body with no query string created a grant, and an
    # `approve: false` sent in the body was silently discarded in favour of the
    # query default. On the one endpoint in the system that creates authority,
    # the absence of an input produced authority. A missing value is now a 422.
    approve: bool
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
async def decide_grant_request(request_id: str, body: DecisionIn):
    """The only endpoint in WARRANT that creates authority.

    The steward check is modelled, not authenticated: it verifies the claimed
    approver stewards the entity, which is not proof of who is calling. Real
    authn belongs in front of this in any deployment - see engine/requests.py.
    """
    assert _svc is not None
    try:
        r = _svc.requests.decide(_svc.model, request_id, approve=body.approve,
                                 decided_by=body.decided_by, note=body.note)
    except PermissionError as exc:
        return JSONResponse(status_code=403, content={"error": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    return asdict(r)


@app.post("/v1/demo/run")
async def demo_run():
    """Run the Expense Auditor against the live plane and return its state.

    Registered only when demo_mode is on; see _demo_guard.

    The real LangGraph graph, the real deterministic decisions, the real replan.
    The only thing stubbed is the transport: `call_fn` reaches the plane
    in-process rather than over HTTP, so the console demo does not require the
    three agent services to be running. `governed_call` covers the HTTP path and
    tests/test_no_bypass.py covers the seam.
    """
    if (blocked := _demo_guard()) is not None:
        return blocked
    assert _svc is not None
    from ..agents.auditor import build_graph
    from ..agents.base import GovernedResult
    from ..agents.fixtures import DATASETS

    async def call_fn(callee: str, purpose: str) -> GovernedResult:
        d = await _svc.evaluate(WarrantRequest("expense-auditor", callee, purpose))
        rows = ({e: DATASETS[callee][e] for e in d.entities_touched
                 if e in DATASETS.get(callee, {})} if d.granted else {})
        return GovernedResult(
            granted=d.granted, warrant_id=d.id, entities=d.entities_touched,
            reasons=[{"code": r.code, "detail": r.detail} for r in d.reasons],
            missing_grants=[{"capability": c, "data_entity": e}
                            for c, e in d.missing_grants],
            justification=d.justification,
            served_by={"tier": d.tier_used, "provider": d.provider_kind,
                       "latency_ms": round(d.latency_ms, 2)},
            data={"rows": rows},
        )

    state = await build_graph(call_fn).ainvoke({})

    # The escalate branch, made durable: what the agent drafted becomes a real
    # request a steward can act on.
    raised = []
    for r in state.get("grant_requests", []):
        try:
            gr = _svc.requests.raise_request(
                _svc.model, capability=r["capability"],
                data_entity=r["data_entity"], requested_by=r["asked_for_by"],
                reason=r["reason"], blocking=r["blocking"])
            raised.append(asdict(gr))
        except ValueError:
            pass        # already granted or already open - both fine

    return {
        "results": [r for r in state.get("results", []) if "replan" not in r],
        "closed": len(state.get("closed", [])),
        "unresolved": len(state.get("unresolved", [])),
        "total": len(state.get("claims", [])),
        "blocked_entities": state.get("blocked_entities", []),
        "grant_requests": raised,
        "report": state.get("report", ""),
    }


@app.post("/v1/demo/reset")
async def demo_reset():
    """Put the demo back to its opening state.

    Needed because the approvals loop is genuinely stateful: once a steward
    grants Employee.Compensation the refusal stops happening, which is the whole
    point - but it also means the demo only works once per deployment without
    this. A judge gets to replay it; so does the video.

    Gated on demo_mode because it DELETES the audit log, and the audit log is
    also the warrant store that callees verify against - so a reset revokes
    every live warrant as well as erasing the evidence of every decision ever
    made. It takes no body and no content-type, so a cross-origin form POST
    reaches it as a CORS simple request with no preflight.
    """
    if (blocked := _demo_guard()) is not None:
        return blocked
    assert _svc is not None
    for f in (_svc.config.audit_path,
              _svc.config.audit_path.parent / "grant_requests.jsonl"):
        if f.exists():
            f.unlink()
    _svc.model = load_model(_svc.config.model_dir)
    return {"ok": True, "grants": len(_svc.model.grants)}


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
