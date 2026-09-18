"""The approvals loop, end to end, against the real model."""
import pytest
from warrant.config import load_config
from warrant.engine.requests import RequestStore
from warrant.model import load_model

CAP, ENT = "expense-management", "Employee.Compensation"


@pytest.fixture
def setup(tmp_path):
    return load_model("config/model"), RequestStore(tmp_path / "gr.jsonl")


def test_raise_then_approve_creates_the_grant(setup):
    m, store = setup
    assert m.has_grant(CAP, ENT) is None
    r = store.raise_request(m, capability=CAP, data_entity=ENT,
                            requested_by="expense-auditor", blocking=6)
    assert r.state == "pending"
    store.decide(m, r.id, approve=True, decided_by="people", note="Q3 close")
    assert m.has_grant(CAP, ENT) is not None


def test_only_the_steward_may_decide(setup):
    m, store = setup
    r = store.raise_request(m, capability=CAP, data_entity=ENT,
                            requested_by="expense-auditor")
    with pytest.raises(PermissionError, match="People & Culture"):
        store.decide(m, r.id, approve=True, decided_by="finance")
    assert m.has_grant(CAP, ENT) is None


def test_cannot_decide_twice(setup):
    m, store = setup
    r = store.raise_request(m, capability=CAP, data_entity=ENT,
                            requested_by="expense-auditor")
    store.decide(m, r.id, approve=False, decided_by="people")
    with pytest.raises(ValueError, match="already declined"):
        store.decide(m, r.id, approve=True, decided_by="people")


def test_unknown_entity_is_rejected(setup):
    m, store = setup
    with pytest.raises(ValueError, match="unknown data entity"):
        store.raise_request(m, capability=CAP, data_entity="Made.Up",
                            requested_by="expense-auditor")


def test_request_for_an_existing_grant_is_rejected(setup):
    m, store = setup
    with pytest.raises(ValueError, match="already exists"):
        store.raise_request(m, capability=CAP, data_entity="Supplier.Contract",
                            requested_by="expense-auditor")


def test_approval_survives_restart(setup, tmp_path):
    m, store = setup
    r = store.raise_request(m, capability=CAP, data_entity=ENT,
                            requested_by="expense-auditor")
    store.decide(m, r.id, approve=True, decided_by="people")
    fresh = load_model("config/model")
    assert fresh.has_grant(CAP, ENT) is None
    fresh.grants.extend(RequestStore(tmp_path / "gr.jsonl").approved_grants())
    assert fresh.has_grant(CAP, ENT) is not None
