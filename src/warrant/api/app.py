"""HTTP surface.

POST /v1/warrant       - request a warrant for an agent-to-agent call
GET  /v1/warrant/{id}  - look one up (callees verify what they were handed)
GET  /v1/grant-requests          - open and decided grant requests
POST /v1/grant-requests          - a refused agent raises one
POST /v1/grant-requests/{id}/decision - the steward approves or declines
POST /v1/demo/run                - run the Expense Auditor against the live plane
GET  /v1/access    - live (judge) or replay; with WARRANT_JUDGE_KEY set, every
                     POST and the live stream need the key
GET  /v1/audit     - the decision log
GET  /v1/model     - the architecture model as a graph (for the UI)
GET  /v1/health    - liveness + which tier is currently serving (/healthz too;
                     Cloud Run reserves that path, so the console uses /v1/health)
GET  /            - the console
"""
from __future__ import annotations

import asyncio
import datetime
import hmac
import json
import os
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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


# Judge-only live runs. On the hosted deployment WARRANT_JUDGE_KEY is set, and
# everything that can spend Token Factory credit - every POST under /v1/ (a
# warrant request classifies with Nemotron, a grant request gets a Steward
# Agent review) and the live stream - needs that key. Everyone else gets the
# recorded live run in static/replay.json, played back in their own browser,
# which spends nothing and touches no shared state. A judge's link carries
# ?key=<code>; the first visit sets a cookie, so the console, the API and the
# live stream just work after that. Unset (local dev, the video capture) means
# open, exactly as before.
_REPLAY = "/static/replay.json"
_COOKIE = "warrant_key"
_live_runs: dict[str, int] = {}


def _judge_key() -> str:
    return os.environ.get("WARRANT_JUDGE_KEY", "")


def _is_judge(supplied: str | None) -> bool:
    key = _judge_key()
    return not key or (bool(supplied) and hmac.compare_digest(supplied.encode(), key.encode()))


def _supplied_key(request: Request) -> str | None:
    # A header for fetch, a query parameter for the first visit (and because
    # EventSource cannot set a header), then the cookie that visit set.
    return (request.headers.get("x-warrant-key") or request.query_params.get("key")
            or request.cookies.get(_COOKIE))


@app.middleware("http")
async def judge_gate(request: Request, call_next):
    p = request.url.path
    spends = (request.method == "POST" and p.startswith("/v1/")) or p == "/v1/demo/stream"
    judge = _is_judge(_supplied_key(request))
    if spends and not judge:
        return JSONResponse(status_code=401, content={
            "error": "judge access code required", "replay": _REPLAY})
    response = await call_next(request)
    if _judge_key() and judge and request.query_params.get("key"):
        # SameSite=Lax: another site cannot make a judge's browser send this
        # cookie on a cross-site POST (e.g. a body-less /v1/demo/run), so the
        # cookie can't be used to spend live runs. Secure behind HTTPS.
        https = request.headers.get("x-forwarded-proto", request.url.scheme) == "https"
        response.set_cookie(_COOKIE, request.query_params["key"], max_age=60 * 86400,
                            httponly=True, secure=https, samesite="lax")
    return response


def _live_cap() -> int:
    return int(os.environ.get("WARRANT_LIVE_DAILY_CAP", "40"))


def _ask_cap() -> int:
    # A free-form request (Ask WARRANT) is 2 model calls, a full audit run ~15,
    # so asks get their own, larger allowance.
    return int(os.environ.get("WARRANT_ASK_DAILY_CAP", "200"))


def _left(kind: str = "run") -> int | None:
    if not _judge_key():
        return None
    today = datetime.date.today().isoformat()  # noqa: DTZ011 - the server's day
    cap = _live_cap() if kind == "run" else _ask_cap()
    return max(0, cap - _live_runs.get(f"{today}:{kind}", 0))


def _take_live_run(kind: str = "run") -> bool:
    """Count a live run ("run") or a free-form request ("ask") against today's
    cap. A backstop if the judge code leaks: the worst case is a fixed number of
    model calls a day, not an open meter.

    ponytail: in-memory, so a restart resets it; the Token Factory spend cap is
    the hard limit behind this one."""
    if not _judge_key():
        return True
    today = datetime.date.today().isoformat()  # noqa: DTZ011 - the server's day
    if not _left(kind):
        return False
    for stale in [k for k in _live_runs if not k.startswith(today)]:
        del _live_runs[stale]
    _live_runs[f"{today}:{kind}"] = _live_runs.get(f"{today}:{kind}", 0) + 1
    return True


@app.get("/v1/access")
async def access(request: Request):
    """Which mode the console should start in: live (judge, or no key
    configured) or replay. Says nothing about the key beyond yes or no."""
    live = _is_judge(_supplied_key(request))
    return {"live": live, "key_required": bool(_judge_key()), "runs_left_today": _left("run"),
            "asks_left_today": _left("ask"), "replay": _REPLAY}


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
    if not _take_live_run("ask"):
        return JSONResponse(status_code=429, content={
            "error": "today's live requests are used up", "replay": _REPLAY})
    req = body.model_dump()
    req["caller_agent"] = caller
    d = await _svc.evaluate(WarrantRequest(**req))
    tiers = _svc.config.tiers
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
                          "model": tiers[d.tier_used].model if d.tier_used in tiers else "",
                          "latency_ms": round(d.latency_ms, 2)},
            "explained_by": {"tier": d.justify_tier, "provider": d.justify_provider,
                             "model": (tiers[d.justify_tier].model
                                       if d.justify_tier in tiers else ""),
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
    """Raised by a refused agent's replan step, or by a judge from Ask WARRANT."""
    assert _svc is not None
    if not _take_live_run("ask"):
        return JSONResponse(status_code=429, content={
            "error": "today's live requests are used up", "replay": _REPLAY})
    try:
        r = _svc.requests.raise_request(_svc.model, **body.model_dump())
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"error": str(exc)})
    await _steward_review(r.id)
    return JSONResponse(status_code=201, content=asdict(_svc.requests.get(r.id)))


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


def _llm(tier: str = "deep", served: dict | None = None):
    """A tier as a plain async text function, or None on the offline profile,
    where the tier is a stub that cannot plan or review. A tier the config does
    not define falls back to deep. `served` records the model that answered,
    which after a router fallback is not necessarily the one asked for."""
    assert _svc is not None
    if tier not in _svc.config.tiers:
        tier = "deep"
    cfg = _svc.config.tiers.get(tier)
    if not cfg or cfg.kind == "mock":
        return None

    async def llm(system: str, user: str, schema: dict | None = None) -> str:
        c = await _svc.router.complete(tier, system, user, json_schema=schema)
        if served is not None:
            served["model"] = c.model
        return c.text
    return llm


async def _steward_review(gr_id: str, on_event=None) -> dict | None:
    """Have the Steward Agent review a request before a person sees it."""
    assert _svc is not None
    from ..agents.steward import review_request
    r = _svc.requests.get(gr_id)
    if r is None or r.state != "pending" or r.review:
        return r.review if r else None
    served: dict = {}
    review = await review_request(
        asdict(r), _svc.model, audit.read_all(_svc.config.audit_path, limit=500),
        [asdict(x) for x in _svc.requests.all()], llm=_llm("review", served))
    review["model"] = served.get("model", "") if review["by_model"] else ""
    _svc.requests.attach_review(gr_id, review)
    if on_event is not None:
        on_event({"t": None, "kind": "review",
                  "text": f"Steward Agent ({review['facts']['steward']}) recommends: "
                          f"{review['recommendation'].replace('_', ' ')}",
                  "data": {k: v for k, v in review.items() if k != "facts"}
                          | {"request_id": gr_id}})
    return review


# One run at a time. Every run spends real Token Factory credit and the hosted
# demo is public, so parallel clicks (or a script) must not multiply the bill.
_RUN_LOCK = asyncio.Lock()
_stream_task: asyncio.Task | None = None


async def _run_auditor(on_event=None) -> dict:
    """Run the Expense Auditor against the live plane.

    The real LangGraph graph, the real deterministic decisions, real Nemotron
    planning. The only shortcut is transport: `call_fn` reaches the plane
    in-process rather than over HTTP, so the console works without the agent
    services running. scripts/smoke_topology.sh covers the cross-process path.
    """
    assert _svc is not None
    from ..agents.auditor import Ctx, build_graph
    from ..agents.base import GovernedResult
    from ..agents.fixtures import DATASETS

    started = time.perf_counter()
    extra_events: list[dict] = []

    def emit(e: dict) -> None:
        """Events from outside the graph (the Steward Agent) get the same clock
        and land in the same trace as the auditor's."""
        if e.get("t") is None:
            e["t"] = round((time.perf_counter() - started) * 1000)
            extra_events.append(e)
        if on_event is not None:
            on_event(e)

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
                       "model": (_svc.config.tiers.get(d.tier_used).model
                                 if d.tier_used in _svc.config.tiers else ""),
                       "latency_ms": round(d.latency_ms, 2)},
            data={"rows": rows},
        )

    # The agent plans, narrows and reports with the deep tier. On the offline
    # profile that tier is a stub that cannot plan, so the graph uses its
    # deterministic fallbacks instead of narrating canned text. Each event
    # arrives on the custom stream as the node emits it; `values` carries the
    # state, of which only the output keys are read below.
    state: dict = {}
    async for mode, chunk in build_graph().astream(
            {}, context=Ctx(call_fn, _llm()), stream_mode=["custom", "values"]):
        if mode == "custom":
            emit(chunk)
        else:
            state = chunk

    # The escalate branch, made durable: what the agent drafted becomes a real
    # request a steward can act on.
    raised = []
    for r in state.get("grant_requests", []):
        try:
            gr = _svc.requests.raise_request(
                _svc.model, capability=r["capability"],
                data_entity=r["data_entity"], requested_by=r["asked_for_by"],
                reason=r["reason"], blocking=r["blocking"])
            await _steward_review(gr.id, on_event=emit)
            raised.append(asdict(_svc.requests.get(gr.id)))
        except ValueError:
            pass        # already granted or already open - both fine

    flagged = state.get("flagged", [])
    return {
        "results": [r for r in state.get("results", []) if "replan" not in r],
        "closed": len(state.get("closed", [])),
        "flagged": flagged,
        "at_risk": round(sum(f["amount"] for f in flagged), 2),
        "unresolved": len(state.get("unresolved", [])),
        "total": len(state.get("claims", [])),
        "blocked_entities": state.get("blocked_entities", []),
        "grant_requests": raised,
        "plan": state.get("plan", []),
        "plan_source": state.get("plan_source", ""),
        "rationale": state.get("rationale", ""),
        "trace": state.get("trace", []) + extra_events,
        "summary": state.get("summary", ""),
        "report": state.get("report", ""),
    }


@app.post("/v1/demo/run")
async def demo_run():
    """Run the auditor and return its full state. Gated on demo_mode."""
    if (blocked := _demo_guard()) is not None:
        return blocked
    if _RUN_LOCK.locked():
        return JSONResponse(status_code=429, content={"error": "a run is already in progress"})
    if not _take_live_run():
        return JSONResponse(status_code=429, content={
            "error": "today's live runs are used up", "replay": _REPLAY})
    async with _RUN_LOCK:
        return await _run_auditor()


@app.get("/v1/demo/stream")
async def demo_stream():
    """The same run, streamed as server-sent events while the agent works, so
    the console shows each plan, warrant, refusal and finding as it happens
    rather than replaying them afterwards. Ends with a `done` event carrying
    the full result."""
    if (blocked := _demo_guard()) is not None:
        return blocked
    if _RUN_LOCK.locked():
        return JSONResponse(status_code=429, content={"error": "a run is already in progress"})
    if not _take_live_run():
        return JSONResponse(status_code=429, content={
            "error": "today's live runs are used up", "replay": _REPLAY})

    # Claim the lock now, before the response starts. Nothing above awaits, and
    # an uncontended acquire does not yield, so a second request arriving at the
    # same moment sees it held and gets the 429. The run starts here too, and
    # the lock is released when the run ends however it ends (finished,
    # failed, cancelled by a disconnect, or cancelled before it ever started).
    await _RUN_LOCK.acquire()
    queue: asyncio.Queue = asyncio.Queue()

    async def worker():
        try:
            result = await _run_auditor(on_event=queue.put_nowait)
            queue.put_nowait({"kind": "done", "result": result})
        except Exception as exc:  # noqa: BLE001 - surface, never hang the stream
            queue.put_nowait({"kind": "error", "text": f"{type(exc).__name__}: {exc}"})

    global _stream_task
    task = _stream_task = asyncio.create_task(worker())   # held: tasks are weakly referenced
    task.add_done_callback(lambda _t: _RUN_LOCK.release())

    async def events():
        try:
            while True:
                ev = await queue.get()
                yield f"data: {json.dumps(ev)}\n\n"
                if ev["kind"] in ("done", "error"):
                    break
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


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


@app.get("/v1/health")
@app.get("/healthz")
async def healthz():
    assert _svc is not None
    return {
        "ok": True,
        "tiers": {name: {"kind": cfg.kind, "model": cfg.model}
                  for name, cfg in _svc.config.tiers.items()},
    }
