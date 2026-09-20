# 0004. The language model never makes the authorization decision

Date: 2026-09-17
Status: Accepted — **one claim in Consequences is corrected by
[ADR-0009](0009-narrowing-can-escalate.md)**; the decision itself stands

## Context

The tempting design is "send the architecture model and the request to Nemotron
and let it decide." It demos quickly. It is also indefensible: a
non-deterministic authorization decision cannot be audited, reproduced, or
trusted, and any judge or security engineer will say so within one question.

## Decision

Grant resolution is **pure, deterministic graph traversal** (`engine/decision.py`
— no I/O, no model call). Nemotron is used for exactly two things:

1. **Classification (fast tier)** — narrow the callee's *declared* data entities
   to those a specific call requires. The result is intersected with the declared
   set, so the model can only narrow, never widen. On any error it fails closed
   to the full declared set.
2. **Justification (deep tier)** — write the paragraph a human reads, from
   reasons already computed. It has a deterministic fallback and cannot change
   the outcome.

Absence of a grant is a denial. WARRANT is fail-closed by construction, including
for agents absent from the model.

## Alternatives considered

- **LLM-as-judge for the whole decision** — rejected. Non-reproducible,
  non-auditable, and vulnerable to prompt injection from the payload.
- **LLM decides, deterministic rules validate afterwards** — rejected. The same
  failure with extra steps; the model still sets the default.
- **No model at all** — rejected. Mapping a free-text purpose and payload onto
  data entities is genuinely a language task, and doing it well is where Nemotron
  earns its place.

## Consequences

- The decision engine is unit-testable with no GPU, credits or network — the
  current suite runs in under a second.
- A prompt-injection attempt in the payload can at worst cause over-inclusion of
  entities, which produces a *denial*, never an escalation.
- We can state plainly in the README: the model explains, it does not decide.
  That sentence is the difference between a demo and something an enterprise
  could conceivably run.
