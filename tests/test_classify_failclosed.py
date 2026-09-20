"""classify.py's fail-closed path, tested directly.

test_ab_demo.py::test_unmatched_purpose_fails_closed passes because the *mock
provider* widens when its token match finds nothing — not because classify.py
does. classify.py could be changed to return an empty set on error and that test
would still be green, while every call it touched would start being granted.

So the fallback is exercised here against stub providers that fail in the ways a
real one does: empty result, malformed JSON, wrong shape, and an unreachable
tier.
"""
from __future__ import annotations

import pytest

from warrant.config import Config, TierConfig
from warrant.model import load_model
from warrant.providers.base import Completion, ProviderUnavailable
from warrant.engine.classify import classify_entities

CALLEE = "roster-planner"
DECLARED = {"Employee.Roster", "Employee.Compensation"}


class _StubRouter:
    """Stands in for TierRouter. `behaviour` decides how the tier misbehaves."""

    def __init__(self, behaviour):
        self.behaviour = behaviour

    async def complete(self, tier, system, user, *, json_schema=None):
        if self.behaviour == "unreachable":
            raise ProviderUnavailable("tier down")
        text = {
            "empty": '{"data_entities": []}',
            "malformed": "not json at all",
            "wrong_shape": '["Employee.Roster"]',
            "null_items": '{"data_entities": [null, 3, "Employee.Roster"]}',
            "not_declared": '{"data_entities": ["Payroll.Secret"]}',
        }[self.behaviour]
        return Completion(text=text, model="stub", tier="fast",
                          provider_kind="stub", latency_ms=1.0)

    async def aclose(self):
        pass


@pytest.mark.parametrize("behaviour", [
    "empty", "malformed", "wrong_shape", "unreachable", "not_declared",
])
async def test_classifier_failure_widens_to_the_declared_set(behaviour):
    """Every failure mode must widen, never narrow. A narrowed set on error
    means grants go unchecked and the call is granted."""
    model = load_model("config/model")
    ents, tier, kind, _ = await classify_entities(
        _StubRouter(behaviour), model, CALLEE, "anything")
    assert set(ents) == DECLARED, (
        f"{behaviour!r} produced {ents} instead of failing closed to the full "
        f"declared set")


async def test_a_partial_result_is_kept_but_never_widened():
    """A usable subset is honoured; junk in the same list is dropped rather
    than reaching the decision engine."""
    model = load_model("config/model")
    ents, _, _, _ = await classify_entities(
        _StubRouter("null_items"), model, CALLEE, "roster only")
    assert set(ents) == {"Employee.Roster"}


async def test_an_entity_the_callee_does_not_declare_cannot_get_through():
    model = load_model("config/model")
    ents, _, _, _ = await classify_entities(
        _StubRouter("not_declared"), model, CALLEE, "anything")
    assert "Payroll.Secret" not in ents
