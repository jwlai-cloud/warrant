"""Wires the pieces into one call: classify -> decide -> justify -> audit."""
from __future__ import annotations

from .config import Config, load_config
from .engine import (WarrantDecision, WarrantRequest, audit, classify_entities,
                     decide, write_justification)
from .engine.requests import RequestStore
from .model import ArchitectureModel, load_model
from .providers import TierRouter, get_router


class WarrantService:
    def __init__(self, config: Config | None = None):
        self.config = config or load_config()
        self.model: ArchitectureModel = load_model(self.config.model_dir)
        self.router: TierRouter = get_router(self.config)
        self.requests = RequestStore(
            self.config.audit_path.parent / "grant_requests.jsonl"
        )
        # Replay approvals so a grant approved in the console survives a
        # restart. The YAML stays the source of truth for the base model; the
        # store is the log of what humans have granted since.
        self.model.grants.extend(self.requests.approved_grants())

    async def evaluate(self, req: WarrantRequest) -> WarrantDecision:
        entities, tier, kind, ms = await classify_entities(
            self.router, self.model, req.callee_agent, req.purpose, req.payload
        )
        d = decide(self.model, req, entities)
        d.tier_used, d.provider_kind, d.latency_ms = tier, kind, ms
        d = await write_justification(self.router, d)
        audit.record(self.config.audit_path, d)
        return d

    async def aclose(self) -> None:
        await self.router.aclose()
