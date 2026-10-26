"""The Steward Agent: reviews grant requests for the data owner, never grants.

It is the second reasoning agent in the system and works for a different
department than the requester. These tests pin what it may and may not do.
"""
from __future__ import annotations

import json

import pytest

from warrant.agents.steward import review_request
from warrant.model import load_model

CAP, ENT = "expense-management", "Employee.Compensation"
REQ = {"id": "R1", "capability": CAP, "data_entity": ENT,
       "requested_by": "expense-auditor", "reason": "close 6 claims", "blocking": 6}
REFUSAL = {"granted": False, "purpose": "allowance vs bands",
           "missing_grants": [{"capability": CAP, "data_entity": ENT}]}


@pytest.fixture
def model():
    return load_model("config/model")


async def test_backed_request_gets_a_conditional_recommendation(model):
    r = await review_request(REQ, model, [REFUSAL], [])
    assert r["recommendation"] == "approve_with_conditions"
    assert r["conditions"] and r["by_model"] is False
    assert r["facts"]["classification"] == "restricted"
    assert r["facts"]["steward"] == "People & Culture"


async def test_unprompted_request_is_declined(model):
    r = await review_request(REQ, model, [], [])
    assert r["recommendation"] == "decline"


async def test_model_cannot_recommend_approval_of_an_unprompted_request(model):
    """The absence of a recorded refusal is a fact, not a judgement call."""
    async def eager(system, user, schema=None):
        return json.dumps({"recommendation": "approve", "conditions": [],
                           "reasoning": "looks fine"})
    r = await review_request(REQ, model, [], [], llm=eager)
    assert r["recommendation"] == "decline" and r["by_model"] is False


async def test_model_recommendation_is_used_when_backed(model):
    async def llm(system, user, schema=None):
        facts = json.loads(user)
        assert facts["blocking_claimed_by_requester"] == 6
        return json.dumps({"recommendation": "approve_with_conditions",
                           "conditions": ["only the six claimants"],
                           "reasoning": "refusal on record; minimise"})
    r = await review_request(REQ, model, [REFUSAL], [], llm=llm)
    assert r["by_model"] and r["conditions"] == ["only the six claimants"]


async def test_previously_declined_pair_is_declined(model):
    hist = [{"id": "R0", "capability": CAP, "data_entity": ENT, "state": "declined"}]
    r = await review_request(REQ, model, [REFUSAL], hist)
    assert r["recommendation"] == "decline" and "R0" in r["reasoning"]


async def test_a_broken_model_still_produces_a_review(model):
    async def broken(system, user, schema=None):
        raise RuntimeError("tier down")
    r = await review_request(REQ, model, [REFUSAL], [], llm=broken)
    assert r["recommendation"] == "approve_with_conditions" and r["by_model"] is False


def test_the_review_never_affects_the_decision(tmp_path, model):
    """decide() must not read the review: a person decides, not the agent."""
    import inspect
    from warrant.engine.requests import RequestStore
    assert "review" not in inspect.getsource(RequestStore.decide)


async def test_a_run_attaches_a_review_and_streams_it(tmp_path, monkeypatch):
    import importlib
    from warrant.config import load_config
    from warrant.service import WarrantService
    cfg = load_config("config/warrant.offline.yaml")
    cfg.audit_path = tmp_path / "warrant.jsonl"
    A = importlib.import_module("warrant.api.app")
    monkeypatch.setattr(A, "_svc", WarrantService(cfg))
    seen = []
    out = await A._run_auditor(on_event=seen.append)
    assert out["grant_requests"] and out["grant_requests"][0]["review"]
    assert out["grant_requests"][0]["state"] == "pending"
    reviews = [e for e in seen if e["kind"] == "review"]
    assert reviews and isinstance(reviews[0]["t"], int)
    assert any(e["kind"] == "review" for e in out["trace"])
