"""Provider protocol. Token Factory and self-hosted vLLM are both
OpenAI-compatible, so one client serves both - the only difference is
base_url, api_key and model name, all of which come from config.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class ProviderUnavailable(RuntimeError):
    """Raised when a tier cannot be reached (e.g. the GPU endpoint is stopped)."""


@dataclass(slots=True)
class Completion:
    text: str
    model: str
    tier: str
    provider_kind: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: float = 0.0


@runtime_checkable
class ChatProvider(Protocol):
    kind: str
    model: str

    async def complete(
        self,
        system: str,
        user: str,
        *,
        json_schema: dict[str, Any] | None = None,
    ) -> Completion: ...
