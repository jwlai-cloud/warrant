"""The Expense Auditor: a planning agent that works across department lines.

It is asked to audit Northwind Group's Q3 expense claims. It cannot do that from
Finance's data alone - checking a supplier invoice needs Operations' contracts,
checking a trip needs People & Culture's roster, checking an allowance needs a
salary band. Every one of those requests goes through `governed_call`, and
WARRANT decides each one deterministically from the architecture model.

What the model does here, and what it does not:

  Nemotron PLANS: reads the claims and a directory of who holds what, decides
  which agents to ask and writes the purpose of each request.
  Nemotron REPLANS: when a request is refused, rewrites it narrowly so the parts
  that ARE permitted still come through, and drafts the grant request for what
  is still blocked.
  Nemotron REPORTS: writes the audit summary from facts the code established.

  Nemotron does NOT decide whether a request is authorised (engine/decision.py
  does, with no model call - ADR-0004), and does NOT decide whether a claim is
  fraudulent. The checks are code. The model decides what to investigate and
  explains what was found.

Graph:

    START -> plan -> gather -> reconcile --(all granted)--> report -> END
                       ^           |                          ^
                       |      (refused, or data             |
                       |       never asked for)             |
                       |           v                          |
                       +--- replan --(nothing to retry)--> escalate
                    (one retry pass)          after the retry pass ^

`replan` asks for data the plan forgot and narrows each refused request once,
then hands those requests back to `gather` with `Command(goto="gather")`. The
loop is bounded by `attempt` in state (MAX_RETRY_PASSES), never by the
recursion limit. The second `reconcile` reports only what the retry newly
found; `escalate` drafts a grant request for what is still blocked and records
the refused path.

Dependencies (`call_fn`, `llm`) arrive per run as `context=Ctx(...)`, the
claims as graph input (the Q3 fixture when absent), so one compiled graph is
safe to reuse. Every event is streamed live through LangGraph's custom stream
and accumulated in `trace`, which the console replays with real timings.

With `llm=None` (tests, the offline profile) every model step falls back to a
deterministic equivalent, so the graph is fully testable without inference.
"""
from __future__ import annotations

import asyncio
import json
import logging
import operator
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import cache
from typing import Annotated, Any, Literal, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from langgraph.types import Command
from pydantic import BaseModel, ValidationError

from .base import GovernedResult
from .fixtures import DATASETS

log_ = logging.getLogger(__name__)

AGENT_ID = "expense-auditor"
CURRENCY = "£"
MAX_RETRY_PASSES = 1          # replan -> gather happens at most this many times

# The plan used when no model is available or the model's plan fails validation.
FALLBACK_PLAN: list[dict[str, str]] = [
    {"callee": "inventory-reconciler",
     "purpose": "supplier contract rates for Q3 claims",
     "why": "verify supplier invoices against contracted day rates"},
    {"callee": "roster-planner",
     "purpose": "which staff travelled in Q3, from the roster",
     "why": "confirm travel bookings fall on rostered trip dates"},
    {"callee": "roster-planner",
     "purpose": "verify allowance claims against employee compensation bands",
     "why": "check allowances against each claimant's band limit"},
]

LLM = Callable[[str, str, "dict | None"], Awaitable[str]]
CallFn = Callable[[str, str], Awaitable[GovernedResult]]


@dataclass(frozen=True)
class Ctx:
    """Per-run dependencies: `call_fn(callee, purpose) -> GovernedResult` and
    `llm(system, user, schema) -> str`, injected so the graph runs against the
    real plane and real inference in the console, and against stubs in tests."""
    call_fn: CallFn
    llm: LLM | None = None


def _merge(a: dict, b: dict) -> dict:
    return {**a, **b}


class AuditInput(TypedDict, total=False):
    claims: list[dict]


class AuditOutput(TypedDict, total=False):
    claims: list[dict]
    plan: list[dict]
    plan_source: str
    rationale: str
    results: Annotated[list[dict], operator.add]
    closed: list[str]
    flagged: list[dict]
    unresolved: list[str]
    grant_requests: list[dict]
    blocked_entities: list[str]
    trace: Annotated[list[dict], operator.add]
    report: str
    summary: str


class AuditState(AuditOutput, total=False):
    t0: float                                       # this run's clock
    pending: list[dict]                             # what the next gather asks
    attempt: int                                    # retry passes taken
    gathered: Annotated[dict[str, Any], _merge]
    refusals: Annotated[list[dict], operator.add]
    blocked_by: dict[str, list[str]]


# ---------------------------------------------------------------- the checks

def _ceiling(contract: dict) -> float:
    """Contracted day rate plus tolerance, for an engagement of up to 4 days."""
    return contract["agreed_day_rate"] * (1 + contract["tolerance_pct"] / 100) * 4


def audit_claims(claims: list[dict], gathered: dict[str, Any]) -> dict[str, Any]:
    """Deterministic audit of every claim against whatever data was granted.

    Returns closed ids, flagged findings, and for every claim that could not be
    checked, the entity it was waiting on. "Degrade" is not a mode: it is this
    function run on less data.
    """
    contracts = {c["supplier_id"]: c for c in gathered.get("Supplier.Contract", [])}
    roster = {r["employee_id"]: set(r["trip_dates"])
              for r in gathered.get("Employee.Roster", [])}
    bands = {b["employee_id"]: b for b in gathered.get("Employee.Compensation", [])}
    have_contracts = "Supplier.Contract" in gathered
    have_roster = "Employee.Roster" in gathered
    have_bands = "Employee.Compensation" in gathered

    closed: list[str] = []
    flagged: list[dict] = []
    blocked: dict[str, list[str]] = {}
    seen: dict[tuple, str] = {}

    def block(entity: str, cid: str) -> None:
        blocked.setdefault(entity, []).append(cid)

    for c in claims:
        cid = c["id"]
        if c["type"] == "supplier":
            key = (c["supplier_id"], c["employee_id"], c["date"], c["amount"])
            if key in seen:                       # Finance's own data suffices
                flagged.append({"claim": cid, "kind": "duplicate",
                                "amount": c["amount"], "evidence": "Expense.Claim",
                                "detail": f"duplicate of {seen[key]} - same supplier, "
                                          f"date and amount"})
                continue
            seen[key] = cid
            if not have_contracts:
                block("Supplier.Contract", cid)
                continue
            contract = contracts.get(c["supplier_id"])
            if contract is None:                  # no contract on file is a query, not a pass
                flagged.append({"claim": cid, "kind": "no-contract",
                                "amount": c["amount"], "evidence": "Supplier.Contract",
                                "detail": f"{c['supplier']} has no contract on file"})
                continue
            if c["amount"] > _ceiling(contract):
                flagged.append({"claim": cid, "kind": "over-contract",
                                "amount": c["amount"], "evidence": "Supplier.Contract",
                                "detail": f"{c['supplier']} billed {CURRENCY}{c['amount']:,.2f}; "
                                          f"contract allows at most "
                                          f"{CURRENCY}{_ceiling(contract):,.2f}"})
                continue
            if c.get("category") == "travel":
                if not have_roster:
                    block("Employee.Roster", cid)
                    continue
                if c["date"] not in roster.get(c["employee_id"], set()):
                    flagged.append({"claim": cid, "kind": "no-rostered-trip",
                                    "amount": c["amount"], "evidence": "Employee.Roster",
                                    "detail": f"travel booked for {c['employee_id']} on "
                                              f"{c['date']}; the roster shows no trip "
                                              f"that day"})
                    continue
            closed.append(cid)
        elif c["type"] == "allowance":
            if not have_bands:
                block("Employee.Compensation", cid)
                continue
            band = bands.get(c["employee_id"])
            if band is None:                      # no band on record is a query, not a pass
                flagged.append({"claim": cid, "kind": "no-band",
                                "amount": c["amount"], "evidence": "Employee.Compensation",
                                "detail": f"{c['employee_id']} has no salary band on record"})
                continue
            limit = band["max_daily_allowance"] * 3
            if c["amount"] > limit:
                flagged.append({"claim": cid, "kind": "over-band",
                                "amount": c["amount"], "evidence": "Employee.Compensation",
                                "detail": f"{CURRENCY}{c['amount']:,.2f} claimed; "
                                          f"{band['band']} caps a 3-day trip at "
                                          f"{CURRENCY}{limit:,.2f}"})
                continue
            closed.append(cid)

    unresolved = [cid for ids in blocked.values() for cid in ids]
    return {"closed": closed, "flagged": flagged, "unresolved": unresolved,
            "blocked_by": blocked}


# ---------------------------------------------------------------- model steps

_PLANNER = (
    "You are the Expense Auditor agent in Northwind Group's Finance department. "
    "You are auditing Q3 expense claims. You can read Finance's own claims, but "
    "verifying them needs data held by other departments' agents, listed in the "
    "directory you are given. Every request you make is judged by WARRANT, an "
    "authorization plane, which may refuse it.\n\n"
    "Plan the data requests this audit genuinely needs. For each one give the "
    "callee, a purpose and why. The purpose is used to judge exactly which data "
    "you will touch, so make it ONE specific sentence naming the data you need "
    "and what you will do with it. Ask for each kind of data in its own request: "
    "a request that mixes data you may see with data you may not is refused "
    "whole. Request everything the audit needs even if you suspect it may be "
    "refused - a refusal tells you who can approve it. At most 4 requests."
)

_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string"},
        "steps": {"type": "array", "minItems": 1, "maxItems": 4, "items": {
            "type": "object",
            "properties": {"callee": {"type": "string"},
                           "purpose": {"type": "string"},
                           "why": {"type": "string"}},
            "required": ["callee", "purpose", "why"],
            "additionalProperties": False}},
    },
    "required": ["rationale", "steps"],
    "additionalProperties": False,
}

_NARROWER = (
    "A data request you made was refused because it would have touched data you "
    "hold no grant to. Rewrite its purpose as ONE specific sentence asking ONLY "
    "for the permitted data listed, and nothing else. Do not mention the refused "
    "data. Return only the sentence."
)

_GAP_FILLER = (
    "You are the Expense Auditor agent. Some claims could not be checked because "
    "your plan never requested the data they need. Write ONE specific sentence "
    "requesting exactly the data named, stating what you will verify with it. "
    "Return only the sentence."
)

_ESCALATOR = (
    "You are the Expense Auditor agent. Draft a short grant request (2-3 "
    "sentences) to the data steward named, asking for read access to the data "
    "entity named. State plainly what audit work is blocked and why the data is "
    "needed. Be specific and factual, do not overstate, do not invent numbers "
    "beyond those given. Return only the request text."
)

_REPORTER = (
    "You are the Expense Auditor agent. Write the audit summary for Northwind "
    "Group's finance controller, in 3-5 plain sentences, from the facts given. "
    "Lead with what needs action. Name the claims flagged and why, the amount "
    "under query, what could not be checked and which department's approval "
    "would unblock it. Use only the facts given; do not invent anything. "
    "Return only the summary."
)


def _directory() -> list[dict]:
    return [{"agent": a, "holds": sorted(ents)} for a, ents in DATASETS.items()
            if a != AGENT_ID]


def _claims_digest(claims: list[dict]) -> str:
    by_cat: dict[str, int] = {}
    for c in claims:
        by_cat[c.get("category", c["type"])] = by_cat.get(c.get("category", c["type"]), 0) + 1
    total = sum(c["amount"] for c in claims)
    return (f"{len(claims)} claims totalling {CURRENCY}{total:,.2f}. By category: "
            + ", ".join(f"{k} {v}" for k, v in sorted(by_cat.items()))
            + ". Supplier claims carry a supplier id; travel bookings and "
              "allowances carry an employee id and a date.")


class _Step(BaseModel):
    callee: str = ""
    purpose: str = ""
    why: str = ""


class _Plan(BaseModel):
    rationale: str = ""
    steps: list[_Step] | None = None


def _valid_plan(raw: _Plan) -> list[dict]:
    """Keep only steps that name a real peer and a usable purpose."""
    peers = {d["agent"] for d in _directory()}
    out, seen = [], set()
    for s in (raw.steps or [])[:4]:
        callee, purpose = s.callee.strip(), s.purpose.strip()[:300]
        if callee not in peers or not purpose or (callee, purpose) in seen:
            continue
        seen.add((callee, purpose))
        out.append({"callee": callee, "purpose": purpose, "why": s.why.strip()[:200]})
    return out


# ---------------------------------------------------------------- helpers

def _event(t0: float, kind: str, text: str, **data) -> dict:
    """One trace event, streamed live (stream_mode="custom") and returned so the
    node can add it to `trace`."""
    event = {"t": round((time.perf_counter() - t0) * 1000), "kind": kind,
             "text": text, **({"data": data} if data else {})}
    get_stream_writer()(event)
    return event


async def _ask(llm: LLM | None, system: str, user: str,
               schema: dict | None = None) -> str | None:
    if llm is None:
        return None
    try:
        out = await llm(system, user, schema)
        return out.strip() if out and out.strip() else None
    except Exception as exc:  # noqa: BLE001 - every model step has a deterministic fallback,
        log_.warning("model step failed, using the fallback: %s: %s",  # but say so
                     type(exc).__name__, exc)
        return None


async def _call(ctx: Ctx, t0: float, step: dict, acc: dict, retry: bool) -> None:
    """One governed request. Appends to `acc` as it completes, so the trace is
    in the order WARRANT answered. A call_fn that raises is recorded as a
    refusal with no missing grants: nothing to escalate, the run goes on."""
    callee, purpose = step["callee"], step["purpose"]
    try:
        r: GovernedResult = await ctx.call_fn(callee, purpose)
    except Exception as exc:  # noqa: BLE001 - a failed call is an outcome, not a crash
        err = f"{type(exc).__name__}: {exc}"
        log_.warning("governed call to %s failed: %s", callee, err)
        acc["results"].append({"callee": callee, "purpose": purpose, "granted": False,
                               "entities": [], "served_by": {}, "retry": retry,
                               "error": err})
        acc["refusals"].append({"callee": callee, "purpose": purpose, "entities": [],
                                "missing": [], "justification": "", "retry": retry,
                                "error": err})
        acc["trace"].append(_event(t0, "refused", f"{callee} did not answer: {err}",
                                   callee=callee, purpose=purpose, entities=[],
                                   missing=[], justification="", served_by={},
                                   retry=retry, error=err))
        return
    acc["results"].append({"callee": callee, "purpose": purpose, "granted": r.granted,
                           "entities": r.entities, "served_by": r.served_by,
                           "retry": retry})
    if r.granted:
        rows = (r.data or {}).get("rows", {}) if isinstance(r.data, dict) else {}
        acc["gathered"].update(rows)
        acc["trace"].append(_event(t0, "granted",
                                   f"{callee} granted {', '.join(r.entities)}",
                                   callee=callee, purpose=purpose, entities=r.entities,
                                   warrant=r.warrant_id, served_by=r.served_by,
                                   retry=retry))
        return
    acc["refusals"].append({"callee": callee, "purpose": purpose, "entities": r.entities,
                            "missing": r.missing_grants,
                            "justification": r.justification, "retry": retry})
    acc["trace"].append(_event(t0, "refused",
                               f"{callee} refused: no grant to "
                               + ", ".join(m["data_entity"] for m in r.missing_grants),
                               callee=callee, purpose=purpose, entities=r.entities,
                               missing=r.missing_grants, justification=r.justification,
                               served_by=r.served_by, retry=retry))


def _unasked_gaps(state: AuditState) -> list[str]:
    """Entities that block claims but that the agent never requested at all.
    A plan can simply forget a kind of data; without this, the claims that
    needed it would end the run unchecked and nobody would be asked."""
    requested = set(state.get("gathered", {}))
    for r in state.get("refusals", []):
        requested |= set(r["entities"])
    return [e for e in state.get("blocked_by", {}) if e not in requested]


# ---------------------------------------------------------------- the nodes

async def plan(state: AuditState, runtime: Runtime[Ctx]) -> dict:
    llm = runtime.context.llm
    t0 = time.perf_counter()
    claims = state.get("claims") or DATASETS[AGENT_ID]["Expense.Claim"]
    trace = [_event(t0, "start", f"Audit Q3 expense claims - {_claims_digest(claims)}")]
    prompt = json.dumps({"task": "Audit Q3 expense claims",
                         "claims": _claims_digest(claims),
                         "directory": _directory()})
    steps, source, rationale, why_fallback = [], "fallback", "", ""
    # Two attempts. Measured against live Nemotron Super, roughly one plan
    # in five came back as valid JSON with an empty steps list; a second
    # ask almost always succeeds, and costs one call only when needed.
    for _attempt in range(2 if llm is not None else 0):
        raw = await _ask(llm, _PLANNER, prompt, _PLAN_SCHEMA)
        if not raw:
            why_fallback = "no response from the model"
            continue
        try:
            parsed = _Plan.model_validate_json(raw)
        except ValidationError as exc:
            why_fallback = ("model plan was not valid JSON"
                            if exc.errors()[0]["type"] == "json_invalid"
                            else "model plan did not match the plan schema")
            continue
        steps = _valid_plan(parsed)
        if steps:
            rationale = parsed.rationale[:400]
            source, why_fallback = "model", ""
            break
        why_fallback = "model plan named no usable requests"
    if not steps:
        steps = FALLBACK_PLAN
        if llm is None:
            why_fallback = "no model configured"
    trace.append(_event(t0, "plan", f"Planned {len(steps)} requests"
                        + (" (Nemotron)" if source == "model"
                           else f" (fallback plan: {why_fallback})"),
                        steps=steps, rationale=rationale, source=source,
                        why_fallback=why_fallback))
    return {"t0": t0, "claims": claims, "plan": steps, "plan_source": source,
            "rationale": rationale, "pending": steps, "attempt": 0,
            "grant_requests": [], "trace": trace}


async def gather(state: AuditState, runtime: Runtime[Ctx]) -> dict:
    """Every pending request at once. They are independent, each costs two
    model calls (classify, justify), and sequentially a 4-request plan spent
    most of the run waiting. Results land in whatever order WARRANT answers."""
    acc: dict = {"results": [], "gathered": {}, "refusals": [], "trace": []}
    retry = state.get("attempt", 0) > 0
    await asyncio.gather(*(_call(runtime.context, state["t0"], step, acc, retry)
                           for step in state["pending"]))
    return acc


async def reconcile(state: AuditState) -> dict:
    a = audit_claims(state["claims"], state.get("gathered", {}))
    retry = state.get("attempt", 0) > 0
    # After the retry pass only what the retry newly found is news; the console
    # adds a finding card per event.
    seen = {f["claim"] for f in state.get("flagged", [])} if retry else set()
    trace = [_event(state["t0"], "finding", f"{f['claim']}: {f['detail']}", finding=f)
             for f in a["flagged"] if f["claim"] not in seen]
    if not retry:
        trace.append(_event(state["t0"], "reconciled",
                            f"{len(a['closed'])} verified, {len(a['flagged'])} flagged, "
                            f"{len(a['unresolved'])} could not be checked",
                            closed=len(a["closed"]), flagged=len(a["flagged"]),
                            blocked={k: len(v) for k, v in a["blocked_by"].items()}))
    return {**a, "trace": trace}


def route(state: AuditState) -> Literal["replan", "escalate", "report"]:
    if state.get("attempt", 0) > 0:
        return "escalate"
    return "replan" if (state.get("refusals") or _unasked_gaps(state)) else "report"


async def replan(state: AuditState,
                 runtime: Runtime[Ctx]) -> Command[Literal["gather", "escalate"]]:
    """Decide what to ask again: data the plan forgot, and the permitted part
    of each refused request. Those go back through `gather` once."""
    llm, t0 = runtime.context.llm, state["t0"]
    trace, retries = [], []

    # 0. Fill gaps: claims blocked on data the plan never asked for.
    holders = {e: d["agent"] for d in _directory() for e in d["holds"]}
    for entity in _unasked_gaps(state):
        callee = holders.get(entity)
        if not callee:
            continue
        n = len(state["blocked_by"].get(entity, []))
        purpose = await _ask(llm, _GAP_FILLER, json.dumps(
            {"data_needed": entity, "claims_waiting": n, "audit": "Q3 expense claims"}))
        by_model = bool(purpose)
        if not purpose:
            purpose = f"{entity} to verify {n} Q3 claims that cannot be checked without it"
        trace.append(_event(t0, "replan", f"{n} claims could not be checked: requesting "
                            f"{entity} from {callee}", gap=entity, new_purpose=purpose,
                            by_model=by_model))
        retries.append({"callee": callee, "purpose": purpose})

    # 1. Narrow: a refused request that also touched permitted data is
    #    reissued asking only for the permitted part.
    for ref in state.get("refusals", []):
        refused = {m["data_entity"] for m in ref["missing"]}
        permitted = [e for e in ref["entities"] if e not in refused]
        if not permitted or ref.get("retry"):
            continue
        purpose = await _ask(llm, _NARROWER, json.dumps(
            {"original_purpose": ref["purpose"], "permitted_data": permitted}))
        by_model = bool(purpose)
        if not purpose:
            purpose = f"{', '.join(permitted)} needed for the Q3 expense audit"
        trace.append(_event(t0, "replan", f"Narrowing request to {ref['callee']}: ask "
                            f"only for {', '.join(permitted)}", refused=sorted(refused),
                            permitted=permitted, new_purpose=purpose, by_model=by_model))
        retries.append({"callee": ref["callee"], "purpose": purpose})

    attempt = state.get("attempt", 0)
    if retries and attempt < MAX_RETRY_PASSES:
        return Command(update={"trace": trace, "pending": retries, "attempt": attempt + 1},
                       goto="gather")
    return Command(update={"trace": trace}, goto="escalate")


async def escalate(state: AuditState, runtime: Runtime[Ctx]) -> dict:
    """Draft a grant request for what is still blocked, addressed to whoever can
    grant it, and record the refused path so the next run does not retry it
    blind. Every refusal counts, the original included even when a narrowed
    retry recovered the permitted part: the refused entity is still blocked."""
    llm, t0 = runtime.context.llm, state["t0"]
    refusals = state.get("refusals", [])
    still_refused = ([r for r in refusals if r.get("retry")]
                     + [r for r in refusals if not r.get("retry")])
    blocked_by = state.get("blocked_by", {})
    trace, requests, seen = [], [], set()
    for ref in still_refused:
        for m in ref["missing"]:
            key = (m["capability"], m["data_entity"])
            if key in seen:
                continue
            seen.add(key)
            n = len(blocked_by.get(m["data_entity"], []))
            text = await _ask(llm, _ESCALATOR, json.dumps({
                "data_entity": m["data_entity"], "requesting_capability": m["capability"],
                "claims_blocked": n, "audit": "Q3 expense claims"}))
            by_model = bool(text)
            if not text:
                text = (f"Close {n} Q3 claims that cannot be verified without "
                        f"{m['data_entity']}.")
            requests.append({"capability": m["capability"],
                             "data_entity": m["data_entity"], "blocking": n,
                             "reason": text[:1500], "asked_for_by": AGENT_ID})
            trace.append(_event(t0, "escalate", f"Grant request drafted for "
                                f"{m['data_entity']} ({n} claims blocked)",
                                data_entity=m["data_entity"], blocking=n,
                                reason=text[:1500], by_model=by_model))
    record = [{"callee": r["callee"], "purpose": r["purpose"],
               "entities": r["entities"], "outcome": "refused"} for r in still_refused]
    return {"grant_requests": requests,
            "blocked_entities": sorted({m["data_entity"] for r in still_refused
                                        for m in r["missing"]}),
            "results": [{"replan": record}], "trace": trace}


async def report(state: AuditState, runtime: Runtime[Ctx]) -> dict:
    total = len(state["claims"])
    closed, flagged = state.get("closed", []), state.get("flagged", [])
    unresolved = state.get("unresolved", [])
    reqs = state.get("grant_requests", [])
    at_risk = sum(f["amount"] for f in flagged)
    facts = {"claims": total, "verified": len(closed),
             "flagged": [{"claim": f["claim"], "issue": f["detail"],
                          "amount": f"{CURRENCY}{f['amount']:,.2f}"} for f in flagged],
             "amount_under_query": f"{CURRENCY}{at_risk:,.2f}",
             "could_not_check": len(unresolved),
             "blocked_on": [{"data": r["data_entity"], "claims": r["blocking"]}
                            for r in reqs]}
    headline = (f"Q3 audit: {len(closed)} of {total} claims verified, "
                f"{len(flagged)} flagged ({CURRENCY}{at_risk:,.2f} under query)")
    if unresolved:
        headline += f", {len(unresolved)} could not be checked"
    lines = [headline + "."]
    lines += [f"- {f['claim']}: {f['detail']}" for f in flagged]
    lines += [f"Grant request: {r['capability']} -> {r['data_entity']} "
              f"({r['blocking']} claims blocked)" for r in reqs]
    narrative = await _ask(runtime.context.llm, _REPORTER, json.dumps(facts))
    event = _event(state["t0"], "report", narrative or headline, facts=facts,
                   by_model=bool(narrative))
    return {"report": "\n".join(lines), "summary": narrative or "", "trace": [event]}


# ---------------------------------------------------------------- the graph

@cache
def build_graph() -> Any:
    """The compiled auditor. It holds no per-run state, so it is built once and
    reused: run it with `ainvoke({"claims": ...}, context=Ctx(call_fn, llm))`,
    or `astream(..., stream_mode=["custom", "values"])` for live events."""
    g = StateGraph(AuditState, context_schema=Ctx,
                   input_schema=AuditInput, output_schema=AuditOutput)
    g.add_node("plan", plan)
    g.add_node("gather", gather)
    g.add_node("reconcile", reconcile)
    g.add_node("replan", replan, destinations=("gather", "escalate"))
    g.add_node("escalate", escalate)
    g.add_node("report", report)
    g.add_edge(START, "plan")
    g.add_edge("plan", "gather")
    g.add_edge("gather", "reconcile")
    g.add_conditional_edges("reconcile", route)
    g.add_edge("escalate", "report")
    g.add_edge("report", END)
    return g.compile()
