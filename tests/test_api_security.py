"""HTTP-layer tests for the endpoints that create or use authority.

These exist because a full review found a critical fail-open default that every
existing test missed: `approve` was a query parameter defaulting to True, so a
body-only POST to the decision endpoint *created a grant*, and an
`approve: false` sent in the body was silently discarded. tests/test_approvals.py
drove `RequestStore.decide()` directly and never crossed the HTTP boundary, so
nothing pinned the wiring between the two.

The lesson generalises: unit tests on the engine do not constrain the API.
"""
from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

from warrant.config import load_config
from warrant.service import WarrantService

CAP, ENT = "expense-management", "Employee.Compensation"


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = load_config("config/warrant.offline.yaml")
    cfg.audit_path = tmp_path / "warrant.jsonl"
    # A real refusal, so a grant request is allowed to exist at all.
    cfg.audit_path.write_text(json.dumps({
        "id": "aaaaaaaa", "granted": False, "caller": "expense-auditor",
        "callee": "roster-planner", "entities_touched": [ENT],
        "missing_grants": [{"capability": CAP, "data_entity": ENT}],
    }) + "\n")
    # importlib, not `from warrant.api import app`: the package __init__
    # re-exports the FastAPI object under that name, so the plain import gets
    # the app instead of the module.
    app_mod = importlib.import_module("warrant.api.app")
    monkeypatch.setattr(app_mod, "_svc", WarrantService(cfg))
    return TestClient(app_mod.app), cfg


def _raise(c) -> str:
    r = c.post("/v1/grant-requests", json={
        "capability": CAP, "data_entity": ENT,
        "requested_by": "expense-auditor", "reason": "x", "blocking": 6})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ------------------------------------------------- the critical fail-open

def test_decision_without_approve_is_rejected_not_approved(client):
    """A well-formed body with no `approve` must be a 422, never a grant."""
    c, _ = client
    rid = _raise(c)
    r = c.post(f"/v1/grant-requests/{rid}/decision",
               json={"decided_by": "people", "note": "n"})
    assert r.status_code == 422, r.text
    assert c.get("/v1/model").json()["grants"] and not any(
        g["capability"] == CAP and g["data_entity"] == ENT
        for g in c.get("/v1/model").json()["grants"]
    ), "a request with no decision created a grant"


def test_decline_in_the_body_actually_declines(client):
    """It used to be discarded in favour of a query default of True."""
    c, _ = client
    rid = _raise(c)
    r = c.post(f"/v1/grant-requests/{rid}/decision",
               json={"decided_by": "people", "approve": False, "note": "no"})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "declined"
    assert not any(g["capability"] == CAP and g["data_entity"] == ENT
                   for g in c.get("/v1/model").json()["grants"])


def test_a_query_string_cannot_override_the_body(client):
    c, _ = client
    rid = _raise(c)
    r = c.post(f"/v1/grant-requests/{rid}/decision?approve=true",
               json={"decided_by": "people", "approve": False})
    assert r.json()["state"] == "declined", "query param still wins over body"


def test_approve_in_the_body_works(client):
    c, _ = client
    rid = _raise(c)
    r = c.post(f"/v1/grant-requests/{rid}/decision",
               json={"decided_by": "people", "approve": True, "note": "ok"})
    assert r.json()["state"] == "approved"
    assert any(g["capability"] == CAP and g["data_entity"] == ENT
               for g in c.get("/v1/model").json()["grants"])


def test_non_steward_is_refused_over_http(client):
    c, _ = client
    rid = _raise(c)
    r = c.post(f"/v1/grant-requests/{rid}/decision",
               json={"decided_by": "finance", "approve": True})
    assert r.status_code == 403


# ------------------------------------------------- forged provenance

def test_forged_grant_request_is_rejected_over_http(client):
    """inventory-control -> Employee.Compensation was never refused, and
    vendor-scout is not expense-management's agent."""
    c, _ = client
    r = c.post("/v1/grant-requests", json={
        "capability": "inventory-control", "data_entity": ENT,
        "requested_by": "expense-auditor", "reason": "urgent", "blocking": 47})
    assert r.status_code == 400
    assert "serves" in r.json()["error"] or "no recorded refusal" in r.json()["error"]


# ------------------------------------------------- demo gating

def test_demo_routes_are_absent_when_demo_mode_is_off(client):
    c, cfg = client
    cfg.demo_mode = False
    assert c.post("/v1/demo/reset").status_code == 404
    assert c.post("/v1/demo/run").status_code == 404


def test_reset_is_available_in_demo_mode(client):
    c, cfg = client
    assert cfg.demo_mode is True
    assert c.post("/v1/demo/reset").status_code == 200


# ------------------------------------------------- caller identity

def test_agent_auth_required_rejects_an_unauthenticated_warrant(client):
    """With agent_auth on, caller_agent in the body is not enough - otherwise
    any client can obtain any agent's warrant, and the callee-side check in
    agents/base.py compares against that same self-asserted value."""
    c, cfg = client
    cfg.agent_auth = "required"
    r = c.post("/v1/warrant", json={"caller_agent": "expense-auditor",
                                    "callee_agent": "roster-planner",
                                    "purpose": "roster"})
    assert r.status_code == 401


def test_token_identifying_another_agent_is_refused(client):
    c, cfg = client
    cfg.agent_auth = "required"
    cfg.agent_tokens = {"tok-inv": "inventory-reconciler"}
    r = c.post("/v1/warrant",
               headers={"Authorization": "Bearer tok-inv"},
               json={"caller_agent": "expense-auditor",
                     "callee_agent": "roster-planner", "purpose": "roster"})
    assert r.status_code == 403
    assert "inventory-reconciler" in r.json()["error"]


def test_valid_token_is_accepted(client):
    c, cfg = client
    cfg.agent_auth = "required"
    cfg.agent_tokens = {"tok-aud": "expense-auditor"}
    r = c.post("/v1/warrant",
               headers={"Authorization": "Bearer tok-aud"},
               json={"caller_agent": "expense-auditor",
                     "callee_agent": "roster-planner",
                     "purpose": "which staff travelled in Q3, from the roster"})
    assert r.status_code in (200, 403)   # authorised; outcome is the engine's call
    assert r.json()["id"]
