"""The decision engine is pure, so it tests without a model, GPU or network."""
from warrant.engine import WarrantRequest, decide
from warrant.model import load_model

MODEL = load_model("config/model")


def test_denies_when_no_grant_covers_the_entity():
    d = decide(MODEL,
               WarrantRequest("expense-auditor", "inventory-reconciler"),
               ["Employee.Compensation"])
    assert d.granted is False
    assert ("expense-management", "Employee.Compensation") in d.missing_grants
    assert any(r.code == "grant_missing" for r in d.reasons)


def test_grants_when_a_cross_org_grant_exists():
    d = decide(MODEL,
               WarrantRequest("expense-auditor", "inventory-reconciler"),
               ["Supplier.Contract"])
    assert d.granted is True
    assert any(r.code == "grant_found" for r in d.reasons)


def test_partial_overlap_still_denies():
    d = decide(MODEL,
               WarrantRequest("expense-auditor", "inventory-reconciler"),
               ["Supplier.Contract", "Employee.Compensation"])
    assert d.granted is False


def test_unmodelled_agent_fails_closed():
    d = decide(MODEL, WarrantRequest("ghost-agent", "roster-planner"), [])
    assert d.granted is False
    assert any(r.code == "unknown_caller" for r in d.reasons)


def test_no_entities_touched_is_granted():
    d = decide(MODEL, WarrantRequest("expense-auditor", "roster-planner"), [])
    assert d.granted is True
