"""The approvals loop: the only code in WARRANT that creates authority.

A grant request is a *response to a recorded refusal*, not a way to ask for
arbitrary access. Three things must hold before one can even be raised - the
requester is a modelled agent, it serves the capability it is asking for, and
the refusal is in the audit log - because the console renders those fields to a
steward as the factual basis for clicking Approve.
"""
import json

import pytest

from warrant.engine.requests import RequestStore
from warrant.model import load_model

CAP, ENT = "expense-management", "Employee.Compensation"
AUDITOR = "expense-auditor"


def _refusal(capability=CAP, data_entity=ENT) -> str:
    """One audit line of the shape engine/audit.py writes for a denial."""
    return json.dumps({
        "id": "aaaaaaaa", "granted": False,
        "caller": AUDITOR, "callee": "roster-planner",
        "entities_touched": [data_entity],
        "missing_grants": [{"capability": capability, "data_entity": data_entity}],
    })


@pytest.fixture
def setup(tmp_path):
    audit = tmp_path / "warrant.jsonl"
    audit.write_text(_refusal() + "\n")
    return load_model("config/model"), RequestStore(tmp_path / "gr.jsonl",
                                                    audit_path=audit)


# ---------------------------------------------------------------- provenance

def test_request_without_a_recorded_refusal_is_rejected(tmp_path):
    """The forgery the review found: any caller could raise a request naming a
    legitimate agent, for a capability it has nothing to do with, and the
    steward would approve on that invented evidence."""
    store = RequestStore(tmp_path / "gr.jsonl", audit_path=tmp_path / "empty.jsonl")
    with pytest.raises(ValueError, match="no recorded refusal"):
        store.raise_request(load_model("config/model"), capability=CAP,
                            data_entity=ENT, requested_by=AUDITOR)


def test_requester_must_be_a_modelled_agent(setup):
    m, store = setup
    with pytest.raises(ValueError, match="not an agent in the model"):
        store.raise_request(m, capability=CAP, data_entity=ENT,
                            requested_by="ghost-agent")


def test_requester_must_serve_the_capability_it_asks_for(setup):
    """vendor-scout serves inventory-control, so it cannot raise a request for
    expense-management's grants even though the refusal is real."""
    m, store = setup
    with pytest.raises(ValueError, match="serves 'inventory-control'"):
        store.raise_request(m, capability=CAP, data_entity=ENT,
                            requested_by="vendor-scout")


def test_a_refusal_for_a_different_pair_does_not_authorise_this_one(tmp_path):
    audit = tmp_path / "warrant.jsonl"
    audit.write_text(_refusal(data_entity="Inventory.StockLevel") + "\n")
    store = RequestStore(tmp_path / "gr.jsonl", audit_path=audit)
    with pytest.raises(ValueError, match="no recorded refusal"):
        store.raise_request(load_model("config/model"), capability=CAP,
                            data_entity=ENT, requested_by=AUDITOR)


# ---------------------------------------------------------------- the loop

def test_raise_then_approve_creates_the_grant(setup):
    m, store = setup
    assert m.has_grant(CAP, ENT) is None
    r = store.raise_request(m, capability=CAP, data_entity=ENT,
                            requested_by=AUDITOR, blocking=6)
    assert r.state == "pending"
    store.decide(m, r.id, approve=True, decided_by="people", note="Q3 close")
    assert m.has_grant(CAP, ENT) is not None


def test_only_the_steward_may_decide(setup):
    m, store = setup
    r = store.raise_request(m, capability=CAP, data_entity=ENT,
                            requested_by=AUDITOR)
    with pytest.raises(PermissionError, match="People & Culture"):
        store.decide(m, r.id, approve=True, decided_by="finance")
    assert m.has_grant(CAP, ENT) is None


def test_cannot_decide_twice(setup):
    m, store = setup
    r = store.raise_request(m, capability=CAP, data_entity=ENT,
                            requested_by=AUDITOR)
    store.decide(m, r.id, approve=False, decided_by="people")
    with pytest.raises(ValueError, match="already declined"):
        store.decide(m, r.id, approve=True, decided_by="people")


def test_unknown_entity_is_rejected(setup):
    m, store = setup
    with pytest.raises(ValueError, match="unknown data entity"):
        store.raise_request(m, capability=CAP, data_entity="Made.Up",
                            requested_by=AUDITOR)


def test_request_for_an_existing_grant_is_rejected(setup):
    m, store = setup
    with pytest.raises(ValueError, match="already exists"):
        store.raise_request(m, capability=CAP, data_entity="Supplier.Contract",
                            requested_by=AUDITOR)


def test_approval_survives_restart(setup, tmp_path):
    m, store = setup
    r = store.raise_request(m, capability=CAP, data_entity=ENT,
                            requested_by=AUDITOR)
    store.decide(m, r.id, approve=True, decided_by="people")
    fresh = load_model("config/model")
    assert fresh.has_grant(CAP, ENT) is None
    fresh.grants.extend(RequestStore(tmp_path / "gr.jsonl").approved_grants())
    assert fresh.has_grant(CAP, ENT) is not None
