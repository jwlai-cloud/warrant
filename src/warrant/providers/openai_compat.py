"""One OpenAI-compatible client, used for BOTH self-hosted vLLM and
Nebius Token Factory.

This is the whole point of ADR-0002: there is no second code path. Switching
a tier between sovereign and managed is a config edit, not a branch.
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import TierConfig
from .base import ChatProvider, Completion, ProviderUnavailable


class OpenAICompatProvider(ChatProvider):
    def __init__(self, tier_name: str, cfg: TierConfig):
        if not cfg.base_url:
            raise ValueError(f"tier '{tier_name}' ({cfg.kind}) has no base_url set")
        self.tier_name = tier_name
        self.kind = cfg.kind
        self.model = cfg.model
        self._cfg = cfg
        self._client = httpx.AsyncClient(
            base_url=cfg.base_url.rstrip("/"),
            timeout=cfg.timeout_s,
            headers={"Authorization": f"Bearer {cfg.api_key or 'none'}"},
        )

    async def complete(self, system: str, user: str, *,
                       json_schema: dict[str, Any] | None = None) -> Completion:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.0,
        }

        # Nemotron thinking-budget control. Served through chat_template_kwargs
        # on vLLM; Token Factory accepts the same shape. TODO(verify) against the
        # Token Factory API reference before the 20 Sep gate.
        if self._cfg.reasoning_budget is not None:
            payload["chat_template_kwargs"] = {
                "reasoning_budget": self._cfg.reasoning_budget
            }

        if json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "warrant_output", "schema": json_schema,
                                "strict": True},
            }

        t0 = time.perf_counter()
        try:
            r = await self._client.post("/chat/completions", json=payload)
            r.raise_for_status()
        except (httpx.HTTPError, httpx.InvalidURL) as exc:
            raise ProviderUnavailable(
                f"tier '{self.tier_name}' ({self.kind}) unreachable: {exc}"
            ) from exc

        data = r.json()
        usage = data.get("usage", {}) or {}
        return Completion(
            text=data["choices"][0]["message"]["content"] or "",
            model=self.model,
            tier=self.tier_name,
            provider_kind=self.kind,
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            reasoning_tokens=(usage.get("completion_tokens_details") or {})
                .get("reasoning_tokens", 0),
            latency_ms=(time.perf_counter() - t0) * 1000,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
