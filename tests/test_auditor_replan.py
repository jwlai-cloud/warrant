"""The Expense Auditor: refused mid-task, then replans - and finds real problems.

Tested as behaviour, not plumbing. The graph runs against a fake `call_fn` and,
by default, no model, so every model step takes its deterministic fallback; the
seam is covered by test_no_bypass.py and live inference by evals/.
"""
from __future__ import annotations

from warrant.agents import fixtures as F
from warrant.agents.auditor import audit_claims, build_graph
from warrant.agents.base import GovernedResult

COMP = "Employee.Compensation"
REFUSAL = [{"capability": "expense-management", "data_entity": COMP}]


def _call_fn(refuse_compensation: bool = True, bundle_roster_with_comp: bool = False):
    """Mirrors the plane. With bundle_roster_with_comp, a request mentioning
    both roster and compensation is refused WHOLE, the way WARRANT refuses a
    call whose entity set includes anything ungranted."""
    async def call(callee: str, purpose: str) -> GovernedResult:
        p = purpose.lower()
        wants_comp = "compensation" in p or "band" in p
        wants_roster = "roster" in p or "travel" in p
        if wants_comp and refuse_compensation:
            ents = ["Employee.Roster", COMP] if (bundle_roster_with_comp and wants_roster) else [COMP]
            return GovernedResult(granted=False, warrant_id="wX", entities=ents,
                                  missing_grants=REFUSAL)
        if wants_comp:
            return GovernedResult(granted=True, warrant_id="w3", entities=[COMP],
                                  data={"rows": {COMP: F.EMPLOYEE_COMPENSATION}})
        if wants_roster:
            return GovernedResult(granted=True, warrant_id="w2", entities=["Employee.Roster"],
                                  data={"rows": {"Employee.Roster": F.EMPLOYEE_ROSTER}})
        return GovernedResult(granted=True, warrant_id="w1", entities=["Supplier.Contract"],
                              data={"rows": {"Supplier.Contract": F.SUPPLIER_CONTRACTS}})
    return call


async def _run(**kw) -> dict:
    return await build_graph(_call_fn(**kw)).ainvoke({})


def _flagged(s) -> set[str]:
    return {f["claim"] for f in s["flagged"]}


# ------------------------------------------------------------ the findings

async def test_finds_every_problem_it_has_the_data_to_see():
    s = await _run()
    assert _flagged(s) == {"CLM-3141", F.OVER_CONTRACT, F.PHANTOM_TRIP}
    kinds = {f["claim"]: f["kind"] for f in s["flagged"]}
    assert kinds["CLM-3141"] == "duplicate"
    assert kinds[F.OVER_CONTRACT] == "over-contract"
    assert kinds[F.PHANTOM_TRIP] == "no-rostered-trip"


async def test_the_refusal_hides_a_real_overpayment():
    """The over-band allowance is invisible without the refused entity - which
    is what makes the refusal matter and the approval worth something."""
    s = await _run()
    assert F.OVER_BAND not in _flagged(s)
    assert len(s["unresolved"]) == 6
    assert set(s["unresolved"]) == {c["id"] for c in F.CLAIMS if c["type"] == "allowance"}


async def test_approving_the_grant_reveals_the_hidden_finding():
    s = await _run(refuse_compensation=False)
    assert F.OVER_BAND in _flagged(s)
    assert s["unresolved"] == []
    assert s["grant_requests"] == []
    assert len(s["closed"]) == 43 and len(s["flagged"]) == 4


async def test_counts_before_approval():
    s = await _run()
    assert len(s["closed"]) == 38 and len(s["flagged"]) == 3


# ------------------------------------------------------------ replanning

async def test_refusal_does_not_stop_the_task():
    s = await _run()
    assert s["closed"], "the agent gave up after a refusal"


async def test_escalation_names_capability_entity_and_real_blocking_count():
    s = await _run()
    assert len(s["grant_requests"]) == 1
    r = s["grant_requests"][0]
    assert (r["capability"], r["data_entity"], r["blocking"]) == ("expense-management", COMP, 6)
    assert COMP in r["reason"]


async def test_a_bundled_refusal_is_narrowed_and_retried():
    """If one request mixes permitted and refused data, WARRANT refuses it
    whole. The agent must reissue it for only the permitted part rather than
    lose the roster - that is replanning, not an if-statement."""
    from warrant.agents import auditor
    original = auditor.FALLBACK_PLAN
    auditor.FALLBACK_PLAN = [
        {"callee": "inventory-reconciler", "purpose": "supplier contract rates", "why": ""},
        {"callee": "roster-planner",
         "purpose": "travel roster and compensation bands for every claimant", "why": ""},
    ]
    try:
        s = await _run(bundle_roster_with_comp=True)
    finally:
        auditor.FALLBACK_PLAN = original
    kinds = [e["kind"] for e in s["trace"]]
    assert "replan" in kinds, "a bundled refusal was not narrowed"
    retried = [r for r in s["results"] if r.get("retry")]
    assert retried and retried[0]["granted"] is True
    assert F.PHANTOM_TRIP in _flagged(s), "the narrowed retry did not recover the roster"


async def test_refused_path_is_recorded():
    s = await _run()
    record = [r for r in s["results"] if "replan" in r]
    assert record and record[0]["replan"][0]["outcome"] == "refused"
    assert s["blocked_entities"] == [COMP]


async def test_trace_tells_the_story_in_order():
    s = await _run()
    kinds = [e["kind"] for e in s["trace"]]
    for a, b in [("start", "plan"), ("plan", "refused"), ("refused", "escalate"),
                 ("escalate", "report")]:
        assert kinds.index(a) < kinds.index(b), f"{a} should precede {b}"
    assert all(isinstance(e["t"], int) for e in s["trace"])


# ------------------------------------------------------------ model steps

async def test_a_bad_model_plan_falls_back_rather_than_failing():
    async def junk_llm(system, user, schema=None):
        return '{"steps": [{"callee": "nonexistent-agent", "purpose": "x", "why": "y"}], "rationale": "r"}'
    s = await build_graph(_call_fn(), llm=junk_llm).ainvoke({})
    assert s["plan_source"] == "fallback"
    assert len(s["flagged"]) == 3


async def test_a_failing_model_never_breaks_the_audit():
    async def broken_llm(system, user, schema=None):
        raise RuntimeError("tier down")
    s = await build_graph(_call_fn(), llm=broken_llm).ainvoke({})
    assert len(s["closed"]) == 38 and s["report"]


async def test_a_model_plan_is_used_when_valid():
    import json as _j
    async def llm(system, user, schema=None):
        if schema:
            return _j.dumps({"rationale": "split by data type", "steps": [
                {"callee": "inventory-reconciler", "purpose": "supplier contract rates", "why": "a"},
                {"callee": "roster-planner", "purpose": "travel roster dates", "why": "b"},
                {"callee": "roster-planner", "purpose": "compensation bands", "why": "c"}]})
        return "model text"
    s = await build_graph(_call_fn(), llm=llm).ainvoke({})
    assert s["plan_source"] == "model" and s["rationale"] == "split by data type"
    assert s["summary"] == "model text"


# ------------------------------------------------------------ the checks

def test_the_contract_ceiling_can_actually_reject():
    contracts = [{"supplier_id": "S", "supplier": "N", "agreed_day_rate": 100.0,
                  "tolerance_pct": 10}]
    base = {"type": "supplier", "supplier_id": "S", "supplier": "N",
            "employee_id": "E", "category": "freight"}
    claims = [{**base, "id": "OK", "date": "d1", "amount": 440.0},
              {**base, "id": "OVER", "date": "d2", "amount": 441.0}]
    a = audit_claims(claims, {"Supplier.Contract": contracts})
    assert a["closed"] == ["OK"] and [f["claim"] for f in a["flagged"]] == ["OVER"]


def test_a_corrupt_approvals_line_does_not_stop_startup(tmp_path):
    from warrant.engine.requests import RequestStore
    f = tmp_path / "gr.jsonl"
    f.write_text('{"not": "a request"}\nnot json at all\n')
    store = RequestStore(f)
    assert store.all() == [] and store.approved_grants() == []
    assert len(store.corrupt) == 2


async def test_a_plan_that_forgets_some_data_is_caught_and_asked_for():
    """Measured live: Nemotron sometimes plans without asking for salary data at
    all. Then nothing is refused, nothing is escalated, and six claims end the
    run silently unchecked. The agent must notice and request what it is
    missing - which WARRANT then refuses, and the escalation follows."""
    import json as _j
    async def forgetful_llm(system, user, schema=None):
        if schema:
            return _j.dumps({"rationale": "contracts and roster only", "steps": [
                {"callee": "inventory-reconciler", "purpose": "supplier contract rates", "why": "a"},
                {"callee": "roster-planner", "purpose": "travel roster dates", "why": "b"}]})
        return None
    s = await build_graph(_call_fn(), llm=forgetful_llm).ainvoke({})
    kinds = [e["kind"] for e in s["trace"]]
    assert "replan" in kinds, "the gap was never noticed"
    gap = [e for e in s["trace"] if e["kind"] == "replan" and e.get("data", {}).get("gap")]
    assert gap and gap[0]["data"]["gap"] == COMP
    assert len(s["grant_requests"]) == 1, "the refused gap was not escalated"
    assert s["grant_requests"][0]["blocking"] == 6


async def test_concurrent_requests_lose_no_events():
    """Requests run concurrently and finish out of order. Each one must still
    leave exactly one granted/refused event - the old per-call copy of the trace
    dropped events as soon as calls overlapped."""
    import asyncio as _a
    base = _call_fn()
    delays = {"supplier": 0.05, "roster": 0.01, "compensation": 0.03}
    async def slow(callee, purpose):
        await _a.sleep(next((d for k, d in delays.items() if k in purpose.lower()), 0.02))
        return await base(callee, purpose)
    s = await build_graph(slow).ainvoke({})
    outcomes = [e for e in s["trace"] if e["kind"] in ("granted", "refused")]
    assert len(outcomes) == len(s["plan"]), [e["text"] for e in outcomes]
    assert len(s["flagged"]) == 3
