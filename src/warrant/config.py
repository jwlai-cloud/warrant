"""Configuration loading with ${ENV_VAR} expansion.

One config file decides whether a tier is served by self-hosted vLLM or by
Nebius Token Factory. Nothing else in the codebase knows the difference.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")

ProviderKind = Literal["vllm", "token_factory", "mock"]


class TierConfig(BaseModel):
    kind: ProviderKind
    base_url: str | None = None
    api_key: str | None = None
    model: str = "mock-model"
    reasoning_budget: int | None = None
    timeout_s: float = 60.0


class Config(BaseModel):
    tiers: dict[str, TierConfig]
    # When true, an entity the classifier dropped that the caller has no grant
    # for is put back, so a call is never granted on the strength of the model
    # having excluded something. Safe and over-restrictive: it denies calls that
    # a correct narrowing would have allowed. Off by default; see ADR-0009.
    strict_narrowing: bool = False
    fallback: dict[str, str | None] = Field(default_factory=dict)
    model_dir: Path = Path("config/model")
    audit_path: Path = Path("audit/warrant.jsonl")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        def sub(m: re.Match[str]) -> str:
            return os.environ.get(m.group(1), "")
        expanded = _ENV_RE.sub(sub, value)
        return expanded or None if _ENV_RE.search(value) and not expanded else expanded
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path or os.environ.get("WARRANT_CONFIG", "config/warrant.yaml"))
    raw = yaml.safe_load(path.read_text())
    return Config.model_validate(_expand(raw))
