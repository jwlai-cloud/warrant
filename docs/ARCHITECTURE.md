# Architecture

## One-paragraph summary

WARRANT sits between agents. When one agent wants to call another, it asks
WARRANT for permission. WARRANT looks the call up in a model of the
organisation — which business capability the calling agent serves, who owns it,
which data entities the called agent touches, who stewards those — and issues
either a signed warrant or a refusal **with the architectural reason**, then
writes an audit record. The decision itself is deterministic graph traversal.
NVIDIA Nemotron models are used to work out which data entities a given call
actually touches, and to write the explanation a human reads.

## Components

**`warrant.model`** — the architecture model: a deliberately small subset of the
TOGAF content metamodel (Organization Unit, Business Capability, Data Entity,
Application Component/Agent, and Grant), loaded from YAML into an in-memory
graph and validated on load. *Not* responsible for any decision logic, and not
a general-purpose EA repository — it holds only what an authorization decision
needs.

**`warrant.engine.decision`** — pure, deterministic grant resolution. Given a
model, a request and a list of data entities, returns a decision with
structured reasons. No I/O, no model call. *Not* responsible for deciding which
entities are touched, or for phrasing anything for humans.

**`warrant.engine.classify`** — fast-tier Nemotron call that narrows the callee's
declared data entities to those a specific call requires. Can only ever
*narrow* the declared set, never widen it, so a hallucination cannot grant
access. Fails closed to the full declared set.

**`warrant.engine.justify`** — deep-tier Nemotron call that turns structured
reasons into one paragraph of prose. *Not* responsible for the outcome; it
explains a decision already made, and has a deterministic fallback.

**`warrant.providers`** — one OpenAI-compatible HTTP client serving both
self-hosted vLLM and Nebius Token Factory, plus a `mock` provider for offline
work. `TierRouter` resolves a logical tier (`fast`, `deep`) to a provider and
falls back when a tier is unreachable.

**`warrant.engine.audit`** — append-only JSONL log of every decision, granted or
refused.

**`warrant.api`** — FastAPI surface: `POST /v1/warrant`, `GET /v1/audit`,
`GET /v1/model`, `GET /healthz`.

**`warrant.cli`** — `ask`, `log`, `validate`, `serve`.

## Data flow

1. Calling agent → WARRANT: `POST /v1/warrant {caller, callee, purpose, payload}`
2. WARRANT → architecture model: look up caller's capability and callee's declared `reads`
3. WARRANT → fast tier (self-hosted Nemotron Nano on vLLM): narrow declared entities to those this call requires
4. Fast tier → WARRANT: subset of data entity ids (JSON schema constrained)
5. WARRANT → decision engine: deterministic grant check, capability × each entity
6. Decision engine → WARRANT: granted/denied plus structured reasons
7. WARRANT → deep tier (Nemotron Super/Ultra on Token Factory): write the justification
8. Deep tier → WARRANT: one paragraph of prose
9. WARRANT → audit log: append the record
10. WARRANT → calling agent: `200` with warrant, or `403` with the refusal and its reason

## External dependencies

- **Nebius Token Factory inference API** — `POST /v1/chat/completions` against
  `nvidia/nemotron-3-super-120b-a12b` (deep tier). Satisfies the hackathon's
  "runtime call to the Token Factory inference API" clause.
- **Nebius AI Cloud Serverless Endpoints** — a GPU endpoint running the
  `vllm/vllm-openai` container serving Nemotron 3 Nano (fast tier), and a
  CPU-only endpoint hosting the API and UI. Satisfies the "deployed/run using
  Nebius AI Cloud compute" clause.
- **NVIDIA Nemotron 3** — Nano (fast) and Super/Ultra (deep). `reasoning_budget`
  is used as a per-tier cost/latency dial.
- **NVIDIA OpenShell** *(planned)* — enforcement layer. WARRANT computes the
  grant; OpenShell's declarative network and inference policy enforces it.

## Deployment topology

| Component | Runs on | Always on? | Cost note |
|---|---|---|---|
| API + UI | Nebius Serverless Endpoint, CPU-only | Yes, through judging | Small continuous bill; endpoints do NOT scale to zero |
| Fast tier (vLLM + Nemotron Nano) | Nebius Serverless Endpoint, 1× L40S | **No — started manually** | ~$0.74/hr preemptible; stopped = no compute charge |
| Deep tier | Nebius Token Factory | Managed | Per token, inside the $50 of hackathon credits |
| Audit log | JSONL on the API container | — | Move to Object Storage before submission |

When the fast tier is stopped, `TierRouter` falls through to the deep tier, the
request still succeeds, and the audit record says which tier served it.

## Known limitations / non-goals

- **Not an agent builder.** That space is saturated and WARRANT is framework-agnostic by design.
- **Not an EA repository.** SAP LeanIX AI Agent Hub (GA Nov 2025) models agents against capability maps; WARRANT deliberately does not compete there. It consumes a model and makes a runtime decision.
- **Not a sandbox or a gateway.** NVIDIA OpenShell is the enforcement layer; WARRANT is the decision layer above it.
- **The model is hand-authored.** Discovery/ingestion from a real EA tool is out of scope for the hackathon window.
- **Grants are coarse** — capability × data entity. No row-level, purpose-limited or time-boxed grants yet.
