"""The agent loop: refused mid-task, then replans.

This is the behaviour ADR-0008 says makes WARRANT a multi-agent system rather
than a proxy demo, so it is tested as behaviour, not as plumbing. The graph runs
against a fake `call_fn` - the seam itself is covered by test_no_bypass.py.
"""
from __future__ import annotations

from warrant.agents.auditor import build_graph
from warrant.agents.base import GovernedResult
from warrant.agents.fixtures import (CLAIMS, EMPLOYEE_COMPENSATION,
                                     EMPLOYEE_ROSTER, SUPPLIER_CONTRACTS)

REFUSAL = [{"capability": "expense-management",
            "data_entity": "Employee.Compensation"}]


def _call_fn(refuse_compensation: bool = True):
    """Mirrors the real plane: grants the first two calls, refuses the third."""
    async def call(callee: str, purpose: str) -> GovernedResult:
        if "compensation" in purpose:
            if refuse_compensation:
                return GovernedResult(
                    granted=False, warrant_id="w3",
                    entities=["Employee.Compensation"],
                    missing_grants=REFUSAL,
                    justification="No grant covers Employee.Compensation.",
                )
            return GovernedResult(
                granted=True, warrant_id="w3",
                entities=["Employee.Compensation"],
                data={"rows": {"Employee.Compensation": EMPLOYEE_COMPENSATION}},
            )
        if "roster" in purpose:
            return GovernedResult(
                granted=True, warrant_id="w2", entities=["Employee.Roster"],
                data={"rows": {"Employee.Roster": EMPLOYEE_ROSTER}})
        return GovernedResult(
            granted=True, warrant_id="w1", entities=["Supplier.Contract"],
            data={"rows": {"Supplier.Contract": SUPPLIER_CONTRACTS}})
    return call


async def _run(refuse: bool = True) -> dict:
    return await build_graph(_call_fn(refuse)).ainvoke({})


async def test_refusal_does_not_stop_the_task():
    """Degrade: the agent closes what the granted data supports."""
    s = await _run()
    assert s["closed"], "agent closed nothing after a refusal - it gave up"
    assert len(s["closed"]) == 41, len(s["closed"])


async def test_exactly_the_allowance_claims_stay_open():
    """The 6 unresolved must be precisely the ones needing the refused entity,
    or 'blocked on Employee.Compensation' is a story rather than a fact."""
    s = await _run()
    assert len(s["unresolved"]) == 6
    allowance = {c["id"] for c in CLAIMS if c["type"] == "allowance"}
    assert set(s["unresolved"]) == allowance


async def test_escalation_names_capability_and_entity():
    """Escalate: a generic 'access denied' is a gimmick; a request naming what
    to grant and why is a product (ADR-0008)."""
    s = await _run()
    reqs = s["grant_requests"]
    assert len(reqs) == 1
    r = reqs[0]
    assert r["capability"] == "expense-management"
    assert r["data_entity"] == "Employee.Compensation"
    assert r["blocking"] == 6
    assert "Employee.Compensation" in r["reason"]


async def test_refused_path_is_recorded():
    """Record: the next run must not retry the refused path blind."""
    s = await _run()
    replan = [r for r in s["results"] if "replan" in r]
    assert replan, "no replan record written"
    assert replan[0]["replan"][0]["outcome"] == "refused"
    assert s["blocked_entities"] == ["Employee.Compensation"]


async def test_granting_the_request_closes_everything():
    """The loop the approvals workflow closes: with the grant in place, the
    same agent on the same task needs no replan."""
    s = await _run(refuse=False)
    assert s["grant_requests"] == []
    assert s["unresolved"] == []
    assert len(s["closed"]) == 47
    assert "47 of 47" in s["report"]
