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
    # Both of these default to the SECURE value, so a config that forgets to
    # mention them is safe. The demo profile opts out of each explicitly, which
    # makes "this deployment is open" a visible choice rather than an omission.
    #
    # agent_auth: when "required", POST /v1/warrant must carry a bearer token
    # that maps to an agent id in `agent_tokens`, and a request whose
    # caller_agent disagrees with the token is rejected. Without this, the
    # caller's identity is a self-asserted string in the request body, so any
    # client can obtain any agent's warrant - and the callee-side check in
    # agents/base.py compares against that same self-asserted value.
    agent_auth: Literal["required", "disabled"] = "required"
    agent_tokens: dict[str, str] = Field(default_factory=dict)  # token -> agent id
    # demo_mode: gates /v1/demo/*, including reset, which DELETES the audit log
    # and the approvals store. The audit log is also the warrant store, so
    # deleting it revokes every live warrant.
    demo_mode: bool = False
    # When true, an entity the classifier dropped that the caller has no grant
    # for is put back, so a call is never granted on the strength of the model
    # having excluded something. Safe and over-restrictive: it denies calls that
    # a correct narrowing would have allowed. Off by default; see ADR-0009.
    strict_narrowing: bool = False
    fallback: dict[str, str | None] = Field(default_factory=dict)
    model_dir: Path = Path("config/model")
    audit_path: Path = Path("audit/warrant.jsonl")


# A value whose ${VAR} references are all unset. Distinct from a literal YAML
# null, which is meaningful: `fallback: {deep: null}` means "fail hard, do not
# fall through to another tier".
_UNSET = object()


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        if not _ENV_RE.search(value):
            return value
        missing = [m.group(1) for m in _ENV_RE.finditer(value)
                   if not os.environ.get(m.group(1))]
        expanded = _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), value)
        # Wholly unresolved -> let the field's own default apply. Returning None
        # here used to make `audit_path: ${WARRANT_AUDIT_PATH}` a hard startup
        # failure whenever that variable was unset, which is exactly what the
        # shipped Dockerfile does.
        return _UNSET if missing and not expanded.strip() else expanded
    if isinstance(value, dict):
        out = {k: _expand(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v is not _UNSET}
    if isinstance(value, list):
        return [v for v in (_expand(x) for x in value) if v is not _UNSET]
    return value


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path or os.environ.get("WARRANT_CONFIG", "config/warrant.yaml"))
    raw = yaml.safe_load(path.read_text())
    expanded = _expand(raw)
    if expanded is _UNSET:
        raise ValueError(f"{path} expanded to nothing")
    return Config.model_validate(expanded)
