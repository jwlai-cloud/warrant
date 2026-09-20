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


def test_external_agent_cannot_reach_restricted_data_even_with_a_grant():
    """`external` used to be recorded and never acted on. An agent outside the
    organisation cannot reach a restricted entity on the strength of an internal
    grant, whichever side of the call it is on."""
    m = load_model("config/model")
    # Give inventory-control an explicit grant to the restricted entity, so the
    # only thing that can deny is the external rule itself.
    from warrant.model.schema import Grant
    m.grants.append(Grant(capability="inventory-control",
                          data_entity="Employee.Compensation",
                          granted_by="test"))
    d = decide(m, WarrantRequest("vendor-scout", "roster-planner"),
               ["Employee.Compensation"])
    assert d.granted is False
    assert any(r.code == "external_restricted" for r in d.reasons)


def test_external_rule_does_not_block_non_restricted_entities():
    m = load_model("config/model")
    d = decide(m, WarrantRequest("vendor-scout", "inventory-reconciler"),
               ["Supplier.Contract"])
    assert d.granted is True
