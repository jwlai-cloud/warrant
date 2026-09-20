"""The Expense Auditor: the agent with a planning loop.

It is asked to close Q3 expense claims. It cannot do that alone - verifying a
claim needs data two other organisation units hold. Every one of those calls
goes through `governed_call`, and one of them is refused.

The refusal is the point. It arrives as structured reasons, not an exception,
and the graph branches on it:

    plan -> gather -> reconcile -> (refused?) -> replan -> report
                                        |                     ^
                                        +--- all granted -----+

`reconcile` closes every claim the data in hand can verify - that is the
**degrade** behaviour, and note that it is not a special mode: it is the normal
task running on a smaller input. `replan` then adds the two things that only
make sense after a refusal: **escalate** (draft a grant request naming the
capability, the entity and the steward who can approve it) and **record** (log
the refused path so the next run does not retry it blind).

Nemotron writes the escalation prose. It does not choose whether the call was
authorised - that was decided deterministically by `engine/decision.py` before
this graph ever saw a refusal (ADR-0004, ADR-0008).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from .base import GovernedResult

AGENT_ID = "expense-auditor"

# What the auditor needs, and who holds it. Each entry becomes one governed
# call. Purposes are written narrowly on purpose: a broad purpose classifies to
# a broad entity set, and a broad entity set is more likely to be refused.
PLAN: list[dict[str, str]] = [
    {"callee": "inventory-reconciler",
     "purpose": "supplier contract rates for Q3 claims",
     "need": "supplier rates"},
    {"callee": "roster-planner",
     "purpose": "which staff travelled in Q3, from the roster",
     "need": "travel roster"},
    {"callee": "roster-planner",
     "purpose": "verify allowance claims against employee compensation bands",
     "need": "salary bands"},
]


class AuditState(TypedDict, total=False):
    claims: list[dict]
    results: list[dict]
    gathered: dict[str, Any]
    refusals: list[dict]
    closed: list[str]
    unresolved: list[str]
    grant_requests: list[dict]
    blocked_entities: list[str]
    report: str


@dataclass(slots=True)
class Refusal:
    callee: str
    purpose: str
    entities: list[str] = field(default_factory=list)
    missing: list[dict] = field(default_factory=list)
    justification: str = ""


def _blocked_by(claims: list[dict], gathered: dict[str, Any]) -> dict[str, list[str]]:
    """Which entity each unclosed claim is actually waiting on.

    The escalate branch used to size every request by the TOTAL unresolved
    count, so two missing entities each claimed to block all of them and the
    steward saw an inflated number as the basis for approving.
    """
    out: dict[str, list[str]] = {}
    if "Supplier.Contract" not in gathered:
        out["Supplier.Contract"] = [c["id"] for c in claims
                                    if c["type"] == "supplier"]
    if "Employee.Compensation" not in gathered:
        out["Employee.Compensation"] = [c["id"] for c in claims
                                        if c["type"] == "allowance"]
    return {k: v for k, v in out.items() if v}


def _reconcile(claims: list[dict], gathered: dict[str, Any]) -> list[str]:
    """Close every claim the data in hand can actually verify.

    This is the task, not a fallback. "Degrade" is not a special mode the agent
    enters when refused - it is this same function running on a smaller input.
    A supplier claim needs the contracted rate; an allowance claim needs the
    claimant's salary band. Whichever entity is missing, the claims that depend
    on it simply stay open.
    """
    contracts = {c["supplier_id"]: c for c in gathered.get("Supplier.Contract", [])}
    bands = {b["employee_id"]: b for b in gathered.get("Employee.Compensation", [])}
    closed = []
    for c in claims:
        if c["type"] == "supplier":
            contract = contracts.get(c["supplier_id"])
            if contract is None:
                continue
            ceiling = contract["agreed_day_rate"] * (1 + contract["tolerance_pct"] / 100)
            # Real check, and every fixture claim happens to pass it - so the
            # 41 in "41 of 47" is the count of supplier claims, not a count of
            # claims that survived scrutiny. tests/test_auditor_replan.py has a
            # case with an out-of-tolerance amount so the branch is not vacuous.
            if c["amount"] <= ceiling * 4:      # up to a 4-day engagement
                closed.append(c["id"])
        elif c["type"] == "allowance":
            band = bands.get(c["employee_id"])
            if band is None:
                continue                         # blocked on Employee.Compensation
            if c["amount"] <= band["max_daily_allowance"] * 3:   # up to 3 days
                closed.append(c["id"])
    return closed


def build_graph(call_fn) -> Any:
    """`call_fn(callee, purpose) -> GovernedResult` is injected so the graph is
    testable without three live services."""

    async def plan(state: AuditState) -> AuditState:
        from .fixtures import CLAIMS
        return {"claims": CLAIMS, "results": [], "gathered": {},
                "refusals": [], "closed": [], "unresolved": [],
                "grant_requests": []}

    async def gather(state: AuditState) -> AuditState:
        gathered = dict(state.get("gathered", {}))
        refusals = list(state.get("refusals", []))
        results = list(state.get("results", []))

        for step in PLAN:
            r: GovernedResult = await call_fn(step["callee"], step["purpose"])
            results.append({
                "callee": step["callee"], "purpose": step["purpose"],
                "granted": r.granted, "entities": r.entities,
                "served_by": r.served_by,
            })
            if r.granted:
                rows = (r.data or {}).get("rows", {}) if isinstance(r.data, dict) else {}
                gathered.update(rows)
            else:
                # Not an error. An input.
                refusals.append({
                    "callee": step["callee"], "purpose": step["purpose"],
                    "need": step["need"], "entities": r.entities,
                    "missing": r.missing_grants, "justification": r.justification,
                })
        return {"gathered": gathered, "refusals": refusals, "results": results}

    async def reconcile(state: AuditState) -> AuditState:
        """Do the work with whatever was granted. Always runs."""
        closed = _reconcile(state["claims"], state.get("gathered", {}))
        unresolved = [c["id"] for c in state["claims"] if c["id"] not in set(closed)]
        return {"closed": closed, "unresolved": unresolved}

    def route(state: AuditState) -> str:
        return "replan" if state.get("refusals") else "report"

    async def replan(state: AuditState) -> AuditState:
        unresolved = state.get("unresolved", [])
        blocked_entities = {
            m["data_entity"] for ref in state["refusals"] for m in ref["missing"]
        }

        # --- escalate: a request addressed to someone who can act on it ---
        blocked_by = _blocked_by(state["claims"], state.get("gathered", {}))
        requests = []
        seen: set[tuple[str, str]] = set()
        for ref in state["refusals"]:
            for m in ref["missing"]:
                key = (m["capability"], m["data_entity"])
                if key in seen:
                    continue      # two refusals naming the same entity is one ask
                seen.add(key)
                n = len(blocked_by.get(m["data_entity"], []))
                requests.append({
                    "capability": m["capability"],
                    "data_entity": m["data_entity"],
                    "blocking": n,
                    "reason": (
                        f"Close {n} Q3 claims that cannot be "
                        f"verified without {m['data_entity']}."
                    ),
                    "asked_for_by": AGENT_ID,
                })

        # --- record: so the next run does not retry the refused path blind ---
        record = [
            {"callee": r["callee"], "purpose": r["purpose"],
             "entities": r["entities"], "outcome": "refused"}
            for r in state["refusals"]
        ]

        return {"grant_requests": requests, "refusals": state["refusals"],
                "results": state["results"] + [{"replan": record}],
                "blocked_entities": sorted(blocked_entities)}

    async def report(state: AuditState) -> AuditState:
        total = len(state["claims"])
        closed = state.get("closed", [])
        unresolved = state.get("unresolved", [])
        reqs = state.get("grant_requests", [])
        lines = [f"Q3 reconciliation: {len(closed)} of {total} claims closed."]
        if unresolved:
            lines.append(
                f"{len(unresolved)} unresolved - blocked on "
                + ", ".join(sorted({r['data_entity'] for r in reqs}))
            )
        for r in reqs:
            lines.append(
                f"Grant request: {r['capability']} -> {r['data_entity']} ({r['reason']})"
            )
        return {"report": "\n".join(lines)}

    g = StateGraph(AuditState)
    g.add_node("plan", plan)
    g.add_node("gather", gather)
    g.add_node("reconcile", reconcile)
    g.add_node("replan", replan)
    g.add_node("report", report)
    g.set_entry_point("plan")
    g.add_edge("plan", "gather")
    g.add_edge("gather", "reconcile")
    g.add_conditional_edges("reconcile", route, {"replan": "replan", "report": "report"})
    g.add_edge("replan", "report")
    g.add_edge("report", END)
    return g.compile()
