"""Provider factory + tier router.

`get_router(config)` returns something that resolves a logical tier name
("fast" / "deep") to a live provider, with a configured fallback so that
stopping the GPU endpoint to save money degrades the system instead of
breaking it.
"""
from __future__ import annotations

from ..config import Config, TierConfig
from .base import ChatProvider, Completion, ProviderUnavailable
from .mock import MockProvider
from .openai_compat import OpenAICompatProvider

__all__ = ["ChatProvider", "Completion", "ProviderUnavailable", "TierRouter",
           "build_provider", "get_router"]


def build_provider(tier_name: str, cfg: TierConfig) -> ChatProvider:
    if cfg.kind == "mock":
        return MockProvider(tier_name, cfg)
    if cfg.kind in ("vllm", "token_factory"):
        return OpenAICompatProvider(tier_name, cfg)
    raise ValueError(f"unknown provider kind: {cfg.kind}")


class TierRouter:
    """Resolves a logical tier to a provider, falling back when unavailable.

    The fallback is what makes 'stop the GPU endpoint between sessions' a safe
    cost-control move rather than an outage: `fast` degrades to `deep`, the
    request still succeeds, and the audit record says which tier served it.
    """

    def __init__(self, config: Config):
        self._config = config
        self._providers = {name: build_provider(name, cfg)
                           for name, cfg in config.tiers.items()}

    def provider(self, tier: str) -> ChatProvider:
        if tier not in self._providers:
            raise KeyError(f"no such tier: {tier}")
        return self._providers[tier]

    async def complete(self, tier: str, system: str, user: str, **kw) -> Completion:
        seen: set[str] = set()
        current = tier
        while current and current not in seen:
            seen.add(current)
            try:
                return await self._providers[current].complete(system, user, **kw)
            except ProviderUnavailable:
                nxt = self._config.fallback.get(current)
                if not nxt:
                    raise
                current = nxt
        raise ProviderUnavailable(f"no reachable tier starting from '{tier}'")

    async def aclose(self) -> None:
        for p in self._providers.values():
            if hasattr(p, "aclose"):
                await p.aclose()


def get_router(config: Config) -> TierRouter:
    return TierRouter(config)
