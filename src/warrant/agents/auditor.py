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

    plan -> gather -> reconcile -> (refused?) -> replan -> report
                                       |                     ^
                                       +--- all granted -----+

`replan` retries narrowed requests, re-runs reconciliation on what that
recovered, escalates what remains blocked, and records the refused path.

Every step appends to `trace`, which the console replays with real timings.

With `llm=None` (tests, the offline profile) every model step falls back to a
deterministic equivalent, so the graph is fully testable without inference.
"""
from __future__ import annotations

import json
import time
from typing import Any, Awaitable, Callable, TypedDict

from langgraph.graph import END, StateGraph

from .base import GovernedResult
from .fixtures import DATASETS

AGENT_ID = "expense-auditor"
CURRENCY = "£"

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


class AuditState(TypedDict, total=False):
    claims: list[dict]
    plan: list[dict]
    plan_source: str
    rationale: str
    results: list[dict]
    gathered: dict[str, Any]
    refusals: list[dict]
    closed: list[str]
    flagged: list[dict]
    unresolved: list[str]
    blocked_by: dict[str, list[str]]
    grant_requests: list[dict]
    blocked_entities: list[str]
    trace: list[dict]
    report: str
    summary: str


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
            if contract and c["amount"] > _ceiling(contract):
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
            limit = band["max_daily_allowance"] * 3 if band else 0
            if band and c["amount"] > limit:
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
        "steps": {"type": "array", "items": {
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


def _valid_plan(raw: dict) -> list[dict]:
    """Keep only steps that name a real peer and a usable purpose."""
    peers = {d["agent"] for d in _directory()}
    out, seen = [], set()
    for s in (raw.get("steps") or [])[:4]:
        callee = str(s.get("callee", "")).strip()
        purpose = str(s.get("purpose", "")).strip()[:300]
        if callee not in peers or not purpose or (callee, purpose) in seen:
            continue
        seen.add((callee, purpose))
        out.append({"callee": callee, "purpose": purpose,
                    "why": str(s.get("why", "")).strip()[:200]})
    return out


# ---------------------------------------------------------------- the graph

def build_graph(call_fn: CallFn, llm: LLM | None = None) -> Any:
    """`call_fn(callee, purpose) -> GovernedResult` and `llm(system, user,
    schema) -> str` are injected, so the graph runs against the real plane and
    real inference in the console, and against stubs in tests."""
    t0 = time.perf_counter()

    def ev(state: AuditState, kind: str, text: str, **data) -> list[dict]:
        trace = list(state.get("trace", []))
        trace.append({"t": round((time.perf_counter() - t0) * 1000), "kind": kind,
                      "text": text, **({"data": data} if data else {})})
        return trace

    async def ask(system: str, user: str, schema: dict | None = None) -> str | None:
        if llm is None:
            return None
        try:
            out = await llm(system, user, schema)
            return out.strip() if out and out.strip() else None
        except Exception:
            return None              # every model step has a deterministic fallback

    async def call(state: AuditState, step: dict, results: list, gathered: dict,
                   refusals: list, label: str = "call") -> AuditState:
        r: GovernedResult = await call_fn(step["callee"], step["purpose"])
        results.append({"callee": step["callee"], "purpose": step["purpose"],
                        "granted": r.granted, "entities": r.entities,
                        "served_by": r.served_by, "retry": label == "retry"})
        if r.granted:
            rows = (r.data or {}).get("rows", {}) if isinstance(r.data, dict) else {}
            gathered.update(rows)
            return {"trace": ev(state, "granted",
                                f"{step['callee']} granted {', '.join(r.entities)}",
                                callee=step["callee"], purpose=step["purpose"],
                                entities=r.entities, warrant=r.warrant_id,
                                served_by=r.served_by, retry=label == "retry")}
        refusals.append({"callee": step["callee"], "purpose": step["purpose"],
                         "entities": r.entities, "missing": r.missing_grants,
                         "justification": r.justification, "retry": label == "retry"})
        return {"trace": ev(state, "refused",
                            f"{step['callee']} refused: no grant to "
                            + ", ".join(m["data_entity"] for m in r.missing_grants),
                            callee=step["callee"], purpose=step["purpose"],
                            entities=r.entities, missing=r.missing_grants,
                            justification=r.justification, served_by=r.served_by,
                            retry=label == "retry")}

    async def plan(state: AuditState) -> AuditState:
        from .fixtures import CLAIMS
        s: AuditState = {"claims": CLAIMS, "results": [], "gathered": {},
                         "refusals": [], "grant_requests": [], "trace": []}
        s["trace"] = ev(s, "start", f"Audit Q3 expense claims - {_claims_digest(CLAIMS)}")
        raw = await ask(_PLANNER, json.dumps({"task": "Audit Q3 expense claims",
                                              "claims": _claims_digest(CLAIMS),
                                              "directory": _directory()}), _PLAN_SCHEMA)
        steps, source, rationale = [], "fallback", ""
        if raw:
            try:
                parsed = json.loads(raw)
                steps = _valid_plan(parsed)
                rationale = str(parsed.get("rationale", ""))[:400]
                source = "model" if steps else "fallback"
            except (json.JSONDecodeError, AttributeError):
                steps = []
        if not steps:
            steps = FALLBACK_PLAN
        s.update(plan=steps, plan_source=source, rationale=rationale)
        s["trace"] = ev(s, "plan", f"Planned {len(steps)} requests"
                        + (" (Nemotron)" if source == "model" else " (fallback plan)"),
                        steps=steps, rationale=rationale, source=source)
        return s

    async def gather(state: AuditState) -> AuditState:
        results, gathered, refusals = [], dict(state["gathered"]), []
        s = dict(state)
        for step in state["plan"]:
            s.update(await call(s, step, results, gathered, refusals))
        return {"results": results, "gathered": gathered, "refusals": refusals,
                "trace": s["trace"]}

    async def reconcile(state: AuditState) -> AuditState:
        a = audit_claims(state["claims"], state["gathered"])
        s = dict(state)
        for f in a["flagged"]:
            s["trace"] = ev(s, "finding", f"{f['claim']}: {f['detail']}", finding=f)
        s["trace"] = ev(s, "reconciled",
                        f"{len(a['closed'])} verified, {len(a['flagged'])} flagged, "
                        f"{len(a['unresolved'])} could not be checked",
                        closed=len(a["closed"]), flagged=len(a["flagged"]),
                        blocked={k: len(v) for k, v in a["blocked_by"].items()})
        return {**a, "trace": s["trace"]}

    def route(state: AuditState) -> str:
        return "replan" if state.get("refusals") else "report"

    async def replan(state: AuditState) -> AuditState:
        s = dict(state)
        results = list(state["results"])
        gathered = dict(state["gathered"])
        still_refused: list[dict] = []

        # 1. Narrow: a refused request that also touched permitted data is
        #    reissued asking only for the permitted part.
        for ref in state["refusals"]:
            refused = {m["data_entity"] for m in ref["missing"]}
            permitted = [e for e in ref["entities"] if e not in refused]
            if permitted and not ref.get("retry"):
                purpose = await ask(_NARROWER, json.dumps(
                    {"original_purpose": ref["purpose"], "permitted_data": permitted}))
                if not purpose:
                    purpose = f"{', '.join(permitted)} needed for the Q3 expense audit"
                s["trace"] = ev(s, "replan",
                                f"Narrowing request to {ref['callee']}: ask only for "
                                f"{', '.join(permitted)}", refused=sorted(refused),
                                permitted=permitted, new_purpose=purpose)
                retry_refusals: list[dict] = []
                s.update(await call(s, {"callee": ref["callee"], "purpose": purpose},
                                    results, gathered, retry_refusals, label="retry"))
                still_refused.extend(retry_refusals)
            still_refused.append(ref)

        # 2. Re-audit with whatever the narrowed requests recovered.
        a = audit_claims(state["claims"], gathered)
        newly = [f for f in a["flagged"]
                 if f["claim"] not in {x["claim"] for x in state.get("flagged", [])}]
        for f in newly:
            s["trace"] = ev(s, "finding", f"{f['claim']}: {f['detail']}", finding=f)

        # 3. Escalate what is still blocked, addressed to whoever can grant it.
        blocked_entities = sorted({m["data_entity"] for r in still_refused
                                   for m in r["missing"]})
        requests, seen = [], set()
        for ref in still_refused:
            for m in ref["missing"]:
                key = (m["capability"], m["data_entity"])
                if key in seen:
                    continue
                seen.add(key)
                n = len(a["blocked_by"].get(m["data_entity"], []))
                text = await ask(_ESCALATOR, json.dumps({
                    "data_entity": m["data_entity"], "requesting_capability": m["capability"],
                    "claims_blocked": n, "audit": "Q3 expense claims"}))
                if not text:
                    text = (f"Close {n} Q3 claims that cannot be verified without "
                            f"{m['data_entity']}.")
                requests.append({"capability": m["capability"],
                                 "data_entity": m["data_entity"], "blocking": n,
                                 "reason": text[:1500], "asked_for_by": AGENT_ID})
                s["trace"] = ev(s, "escalate",
                                f"Grant request drafted for {m['data_entity']} "
                                f"({n} claims blocked)", data_entity=m["data_entity"],
                                blocking=n, reason=text[:1500])

        # 4. Record, so the next run does not retry the refused path blind.
        record = [{"callee": r["callee"], "purpose": r["purpose"],
                   "entities": r["entities"], "outcome": "refused"}
                  for r in still_refused]
        return {**a, "results": results + [{"replan": record}], "gathered": gathered,
                "grant_requests": requests, "blocked_entities": blocked_entities,
                "trace": s["trace"]}

    async def report(state: AuditState) -> AuditState:
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
        narrative = await ask(_REPORTER, json.dumps(facts))
        s = dict(state)
        s["trace"] = ev(s, "report", narrative or headline, facts=facts)
        return {"report": "\n".join(lines), "summary": narrative or "",
                "trace": s["trace"]}

    g = StateGraph(AuditState)
    for name, fn in (("plan", plan), ("gather", gather), ("reconcile", reconcile),
                     ("replan", replan), ("report", report)):
        g.add_node(name, fn)
    g.set_entry_point("plan")
    g.add_edge("plan", "gather")
    g.add_edge("gather", "reconcile")
    g.add_conditional_edges("reconcile", route, {"replan": "replan", "report": "report"})
    g.add_edge("replan", "report")
    g.add_edge("report", END)
    return g.compile()

