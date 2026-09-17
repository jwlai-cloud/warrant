# 0002. Serve vLLM and Token Factory through one OpenAI-compatible interface

Date: 2026-09-17
Status: Accepted

## Context

Two tiers are needed: a sovereign fast tier (self-hosted Nemotron Nano on vLLM)
and a managed deep tier (Nemotron Super/Ultra on Nebius Token Factory). Nebius
Serverless Endpoints do **not** scale to zero — autoscaling is roadmapped Q4+
2026 — so the GPU endpoint will be started and stopped manually to control cost,
meaning the sovereign tier is *frequently absent by design*.

The obvious trap is two codepaths that drift, and a November retrofit to unify them.

## Decision

We will implement **one** `OpenAICompatProvider` used for both vLLM and Token
Factory. A tier's `kind`, `base_url`, `api_key` and `model` come from
`config/warrant.yaml`. A `TierRouter` resolves logical tiers (`fast`, `deep`) and
follows a configured fallback when a tier is unreachable. A third `mock` provider
makes the whole system runnable with no GPU, no credits and no network.

## Alternatives considered

- **Separate `VLLMProvider` and `TokenFactoryProvider` classes** — rejected. Both
  speak the same OpenAI-compatible `/v1/chat/completions`; two classes would be
  identical code with different defaults, and would drift.
- **An LLM framework's abstraction (LangChain/LiteLLM)** — rejected for the core.
  It adds a dependency and an opinion for something that is ~80 lines of `httpx`,
  and WARRANT's selling point is being framework-agnostic.
- **Fail hard when a tier is down** — rejected. That would make "stop the GPU to
  save money" an outage. Fallback makes it a degradation, and the audit record
  names the tier that actually served the request.

## Consequences

- Switching a tier between sovereign and managed is a config edit; there is no
  second code path to keep in sync.
- The UI can show which tier served each decision, which puts the self-hosting
  work *inside* the product rather than in a README appendix.
- Benchmarking self-hosted against managed is a config swap plus a timer, so the
  cost/latency comparison comes almost free.
- `reasoning_budget` in `warrant.yaml` is a logical dial, not a wire field. It
  is sent as vLLM's top-level `thinking_token_budget` sampling parameter. The
  scaffold's original `chat_template_kwargs` shape was wrong and has been
  corrected; see ADR-0006. Token Factory does not document the parameter, so the
  dial is effectively vLLM-only - one code path, one field, differing reach.
