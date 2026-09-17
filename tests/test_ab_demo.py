"""The purpose must change the outcome.

This is the test that would have caught the defect the scaffold shipped with:
the classifier narrowed nothing, so every call to a given callee produced the
same decision and Nemotron was inert. If this file ever goes green with
classification disabled, the model has stopped being load-bearing.
"""
import pytest

from warrant.config import load_config
from warrant.engine import WarrantRequest
from warrant.service import WarrantService

# The A/B lives on roster-planner, where People & Culture stewards both the
# roster and the salary bands. Finance may see who travelled, not what they
# earn - so the same agent pair flips on the purpose alone.
PAIR = ("expense-auditor", "roster-planner")
GRANTED_PURPOSE = "which employees travelled in Q3, from the employee roster"
DENIED_PURPOSE = "verify allowance claims against employee compensation bands"


@pytest.fixture
def svc():
    return WarrantService(load_config("config/warrant.offline.yaml"))


async def test_narrow_purpose_is_granted(svc):
    d = await svc.evaluate(WarrantRequest(*PAIR, purpose=GRANTED_PURPOSE))
    assert d.granted is True
    assert d.entities_touched == ["Employee.Roster"]


async def test_purpose_reaching_salary_data_is_denied(svc):
    d = await svc.evaluate(WarrantRequest(*PAIR, purpose=DENIED_PURPOSE))
    assert d.granted is False
    assert ("expense-management", "Employee.Compensation") in d.missing_grants


async def test_same_agents_opposite_outcomes(svc):
    """The whole demo in one assertion: only the purpose differs."""
    a = await svc.evaluate(WarrantRequest(*PAIR, purpose=GRANTED_PURPOSE))
    b = await svc.evaluate(WarrantRequest(*PAIR, purpose=DENIED_PURPOSE))
    assert a.granted != b.granted


async def test_unmatched_purpose_fails_closed(svc):
    """A purpose that classifies to nothing must widen to the declared set,
    never to an empty set - an empty set would be granted by default."""
    d = await svc.evaluate(WarrantRequest(*PAIR, purpose="zzzz"))
    assert d.granted is False
