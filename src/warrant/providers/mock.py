"""Deterministic offline provider. Lets the decision engine, the API and the
whole test suite run with no GPU, no credits and no network."""
from __future__ import annotations

import json
from typing import Any

from ..config import TierConfig
from .base import ChatProvider, Completion


class MockProvider(ChatProvider):
    def __init__(self, tier_name: str, cfg: TierConfig):
        self.tier_name = tier_name
        self.kind = "mock"
        self.model = cfg.model or "mock-model"

    async def complete(self, system: str, user: str, *,
                       json_schema: dict[str, Any] | None = None) -> Completion:
        if json_schema is not None:
            # Entity classification: echo back whatever the prompt listed as
            # the callee's declared reads. Deterministic and dependency-free.
            declared = [ln.strip("- ").strip()
                        for ln in user.splitlines() if ln.strip().startswith("- ")]
            text = json.dumps({"data_entities": declared})
        else:
            text = ("Decision computed from the architecture model; "
                    "see the structured reasons in the audit record.")
        return Completion(text=text, model=self.model, tier=self.tier_name,
                          provider_kind="mock", latency_ms=0.1)
