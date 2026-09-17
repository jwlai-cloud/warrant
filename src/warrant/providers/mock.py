"""Deterministic offline provider. Lets the decision engine, the API and the
whole test suite run with no GPU, no credits and no network.

It is a STUB, not a small model. It narrows by literal token overlap on each
entity's distinguishing segment, so the
offline demo shows the *mechanism* (purpose changes which entities are
considered, which changes the outcome) without pretending to show inference.
Anything phrased indirectly - "headcount cost" for Employee.Compensation -
will not match here and will match on a real fast tier. That gap is the point:
if the offline and online runs agree on every input, the model is doing
nothing.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..config import TierConfig
from .base import ChatProvider, Completion


def _tokens(text: str) -> set[str]:
    """`reconcile stock levels` -> {reconcile, stock, levels}."""
    spaced = re.sub(r"(?<!^)(?=[A-Z])", " ", text.replace(".", " "))
    return {t.lower() for t in re.findall(r"[A-Za-z]+", spaced)}


def _distinguishing(entity_id: str) -> set[str]:
    """Tokens that tell an entity apart from its siblings.

    Only the segment after the final dot. `Employee.Roster` and
    `Employee.Compensation` share the family prefix `Employee`, so matching on
    the whole id makes any mention of "employee" select both - which silently
    widens the set and denies a call that should have been granted.
    """
    return _tokens(entity_id.rsplit(".", 1)[-1])


class MockProvider(ChatProvider):
    def __init__(self, tier_name: str, cfg: TierConfig):
        self.tier_name = tier_name
        self.kind = "mock"
        self.model = cfg.model or "mock-model"

    async def complete(self, system: str, user: str, *,
                       json_schema: dict[str, Any] | None = None) -> Completion:
        if json_schema is not None:
            declared = [ln.strip("- ").strip()
                        for ln in user.splitlines() if ln.strip().startswith("- ")]
            purpose = ""
            for ln in user.splitlines():
                if ln.startswith("Purpose of the call:"):
                    purpose = ln.split(":", 1)[1]
            words = _tokens(purpose)
            narrowed = [e for e in declared if _distinguishing(e) & words]
            # Fail closed, exactly as classify.py does: a purpose that matches
            # nothing is treated as touching everything the callee can read.
            text = json.dumps({"data_entities": narrowed or declared})
        else:
            text = ("Decision computed from the architecture model; "
                    "see the structured reasons in the audit record.")
        return Completion(text=text, model=self.model, tier=self.tier_name,
                          provider_kind="mock", latency_ms=0.1)
